import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.realtime.pubsub.base import MessageCallback
from app.infrastructure.realtime.pubsub.factory import get_pubsub_broker
from app.infrastructure.realtime.pubsub.in_memory import InMemoryPubSubBroker
from app.infrastructure.realtime.pubsub.postgres import (
    PostgresListenNotifyBroker,
)

# --- Testes de InMemoryPubSubBroker ---


@pytest.mark.asyncio
async def test_in_memory_pubsub_connect_and_disconnect() -> None:
    broker = InMemoryPubSubBroker()
    assert broker._is_connected is False

    await broker.connect()
    assert broker._is_connected is True

    # Adiciona inscrição
    mock_cb: MessageCallback = AsyncMock()
    await broker.subscribe("canal_1", mock_cb)
    assert "canal_1" in broker._listeners

    await broker.disconnect()
    assert broker._is_connected is False
    assert len(broker._listeners) == 0


@pytest.mark.asyncio
async def test_in_memory_pubsub_publish_and_subscribe_multiple() -> None:
    broker = InMemoryPubSubBroker()
    await broker.connect()

    received_1: list[dict[str, Any]] = []
    received_2: list[dict[str, Any]] = []

    async def cb1(msg: dict[str, Any]) -> None:
        received_1.append(msg)

    async def cb2(msg: dict[str, Any]) -> None:
        received_2.append(msg)

    await broker.subscribe("turma_x", cb1)
    await broker.subscribe("turma_x", cb2)

    payload = {"type": "new_message", "text": "olá mundo"}
    await broker.publish("turma_x", payload)

    assert len(received_1) == 1
    assert received_1[0] == payload
    assert len(received_2) == 1
    assert received_2[0] == payload


@pytest.mark.asyncio
async def test_in_memory_pubsub_publish_empty_channel_no_error() -> None:
    broker = InMemoryPubSubBroker()
    await broker.connect()
    # Publicar em canal sem inscritos não deve causar erro
    await broker.publish("canal_fantasma", {"data": 123})


@pytest.mark.asyncio
async def test_in_memory_pubsub_unsubscribe_single_and_all() -> None:
    broker = InMemoryPubSubBroker()
    await broker.connect()

    mock_cb1: MessageCallback = AsyncMock()
    mock_cb2: MessageCallback = AsyncMock()

    await broker.subscribe("sala", mock_cb1)
    await broker.subscribe("sala", mock_cb2)
    assert len(broker._listeners["sala"]) == 2

    # Desinscreve apenas cb1
    await broker.unsubscribe("sala", mock_cb1)
    assert len(broker._listeners["sala"]) == 1
    assert mock_cb1 not in broker._listeners["sala"]

    # Desinscreve todos do canal com callback=None
    await broker.unsubscribe("sala")
    assert "sala" not in broker._listeners

    # Desinscrever canal inexistente não quebra
    await broker.unsubscribe("inexistente")


@pytest.mark.asyncio
async def test_in_memory_pubsub_callback_exception_isolation() -> None:
    broker = InMemoryPubSubBroker()
    await broker.connect()

    failing_cb = AsyncMock(side_effect=RuntimeError("Falha proposital"))
    working_cb = AsyncMock()

    await broker.subscribe("canal_falha", failing_cb)
    await broker.subscribe("canal_falha", working_cb)

    # Publica: working_cb deve ser chamado mesmo com erro no failing_cb
    await broker.publish("canal_falha", {"hello": "world"})

    failing_cb.assert_awaited_once()
    working_cb.assert_awaited_once_with({"hello": "world"})


# --- Testes de PostgresListenNotifyBroker ---


def test_postgres_broker_clean_dsn() -> None:
    dsn_asyncpg = "postgresql+asyncpg://postgres:pass@localhost:5432/db"
    assert (
        PostgresListenNotifyBroker._clean_dsn(dsn_asyncpg)
        == "postgresql://postgres:pass@localhost:5432/db"
    )

    dsn_pg_asyncpg = "postgres+asyncpg://user:pass@host:5432/db"
    assert (
        PostgresListenNotifyBroker._clean_dsn(dsn_pg_asyncpg)
        == "postgresql://user:pass@host:5432/db"
    )

    dsn_native = "postgresql://user:pass@host:5432/db"
    assert PostgresListenNotifyBroker._clean_dsn(dsn_native) == dsn_native


@pytest.mark.asyncio
async def test_postgres_broker_publish_large_payload_fallback_to_refetch() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    broker._is_connected = True
    mock_pool = AsyncMock()
    broker._pool = mock_pool

    msg_id = str(uuid.uuid4())
    huge_payload = {
        "type": "new_message",
        "data": {"id": msg_id, "content": "x" * 8100},
    }
    await broker.publish("classroom:456", huge_payload)

    mock_pool.execute.assert_awaited_once()
    call_args = mock_pool.execute.call_args[0]
    assert call_args[0] == "SELECT pg_notify($1, $2)"
    assert call_args[1] == "classroom:456"
    dispatched_payload = json.loads(call_args[2])
    assert dispatched_payload["type"] == "message_refetch"
    assert dispatched_payload["message_id"] == msg_id


@pytest.mark.asyncio
async def test_postgres_broker_connect_and_disconnect_lifecycle() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    mock_pool = AsyncMock()
    mock_listener = AsyncMock()
    mock_listener.is_closed = MagicMock(return_value=False)

    with (
        patch("asyncpg.create_pool", AsyncMock(return_value=mock_pool)),
        patch("asyncpg.connect", AsyncMock(return_value=mock_listener)),
    ):
        await broker.connect()
        assert broker._is_connected is True

        # Segunda chamada a connect() deve ser no-op
        await broker.connect()

        # Inscreve um callback simulado
        cb: MessageCallback = AsyncMock()
        await broker.subscribe("chan_test", cb)
        mock_listener.add_listener.assert_awaited_once()

        await broker.disconnect()
        assert broker._is_connected is False
        mock_listener.remove_listener.assert_awaited_once()
        mock_listener.close.assert_awaited_once()
        mock_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_postgres_broker_raw_notification_handler_dispatch() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    cb1: MessageCallback = AsyncMock()
    cb2: MessageCallback = AsyncMock()
    broker._listeners["classroom:123"] = {cb1, cb2}

    payload = json.dumps({"type": "test_event", "value": 42})
    await broker._raw_notification_handler(
        connection=AsyncMock(),
        pid=1234,
        channel="classroom:123",
        payload=payload,
    )

    expected = {"type": "test_event", "value": 42}
    cb1.assert_awaited_once_with(expected)
    cb2.assert_awaited_once_with(expected)


@pytest.mark.asyncio
async def test_postgres_broker_raw_notification_handler_invalid_json() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    cb: MessageCallback = AsyncMock()
    broker._listeners["test_channel"] = {cb}

    # JSON corrompido não quebra a aplicação nem aciona callbacks
    await broker._raw_notification_handler(
        connection=AsyncMock(),
        pid=1234,
        channel="test_channel",
        payload="not-valid-json{{{",
    )
    cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_postgres_broker_raw_notification_handler_isolated_errors() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    failing_cb = AsyncMock(side_effect=RuntimeError("Erro no callback"))
    working_cb = AsyncMock()
    broker._listeners["test_chan"] = {failing_cb, working_cb}

    await broker._raw_notification_handler(
        connection=AsyncMock(),
        pid=1234,
        channel="test_chan",
        payload='{"status": "ok"}',
    )

    failing_cb.assert_awaited_once()
    working_cb.assert_awaited_once_with({"status": "ok"})


@pytest.mark.asyncio
async def test_postgres_broker_subscribe_and_unsubscribe_listener_calls() -> None:
    broker = PostgresListenNotifyBroker(dsn="postgresql://localhost/fake")
    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    broker._listener_conn = mock_conn
    broker._is_connected = True

    cb1: MessageCallback = AsyncMock()
    cb2: MessageCallback = AsyncMock()

    # 1º subscribe adiciona listener no postgres
    await broker.subscribe("room_1", cb1)
    mock_conn.add_listener.assert_awaited_once_with(
        "room_1", broker._raw_notification_handler
    )

    # 2º subscribe para a mesma sala não adiciona outro listener no postgres
    mock_conn.add_listener.reset_mock()
    await broker.subscribe("room_1", cb2)
    mock_conn.add_listener.assert_not_awaited()

    # Desinscreve cb1: postgres ainda ouve porque cb2 permanece
    await broker.unsubscribe("room_1", cb1)
    mock_conn.remove_listener.assert_not_awaited()

    # Desinscreve cb2: remove do postgres
    await broker.unsubscribe("room_1", cb2)
    mock_conn.remove_listener.assert_awaited_once_with(
        "room_1", broker._raw_notification_handler
    )


# --- Testes do Factory get_pubsub_broker ---


def test_get_pubsub_broker_in_memory() -> None:
    broker = get_pubsub_broker("in_memory")
    assert isinstance(broker, InMemoryPubSubBroker)


def test_get_pubsub_broker_postgres() -> None:
    broker = get_pubsub_broker("postgres")
    assert isinstance(broker, PostgresListenNotifyBroker)
