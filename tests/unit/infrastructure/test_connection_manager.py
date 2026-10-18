import uuid
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocket

from app.infrastructure.realtime.connection_manager import ConnectionManager

# --- Testes de ConnectionManager com Broker Injetado ---


@pytest.mark.asyncio
async def test_connection_manager_with_custom_broker_publishes(
    mock_pubsub_broker: AsyncMock,
) -> None:
    mock_broker = mock_pubsub_broker
    manager = ConnectionManager(broker=mock_broker)
    room_id = uuid.uuid4()

    mock_ws = AsyncMock()
    await manager.connect(room_id, mock_ws)
    mock_broker.subscribe.assert_awaited_once()

    # Segundo connect na mesma sala não reinscreve no broker
    mock_broker.subscribe.reset_mock()
    mock_ws2 = AsyncMock()
    await manager.connect(room_id, mock_ws2)
    mock_broker.subscribe.assert_not_awaited()

    # Broadcast delega para broker.publish
    payload = {"event": "chat_message", "id": "123"}
    await manager.broadcast(room_id, payload)
    mock_broker.publish.assert_awaited_once_with(f"classroom:{room_id}", payload)

    # Desconecta 1º socket: não desinscreve ainda
    await manager.disconnect(room_id, mock_ws)
    mock_broker.unsubscribe.assert_not_awaited()

    # Desconecta 2º socket: esvazia sala e desinscreve no broker
    await manager.disconnect(room_id, mock_ws2)
    mock_broker.unsubscribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_manager_shutdown_and_broker_property(
    mock_pubsub_broker: AsyncMock,
) -> None:
    mock_broker = mock_pubsub_broker
    manager = ConnectionManager(broker=mock_broker)
    assert manager.broker is mock_broker

    room_id = uuid.uuid4()
    mock_ws = AsyncMock()
    await manager.connect(room_id, mock_ws)
    assert room_id in manager._rooms

    await manager.shutdown()
    assert len(manager._rooms) == 0
    assert len(manager._room_callbacks) == 0
    mock_broker.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_manager_connect_and_disconnect(
    mock_pubsub_broker: AsyncMock,
) -> None:
    manager = ConnectionManager(broker=mock_pubsub_broker)
    room_id = uuid.uuid4()
    mock_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, mock_ws)
    assert room_id in manager._rooms
    assert mock_ws in manager._rooms[room_id]

    await manager.disconnect(room_id, mock_ws)
    assert room_id not in manager._rooms


@pytest.mark.asyncio
async def test_connection_manager_when_broker_delivers_should_send_to_clients(
    mock_pubsub_broker: AsyncMock,
) -> None:
    manager = ConnectionManager(broker=mock_pubsub_broker)
    room_id = uuid.uuid4()
    ws1 = AsyncMock(spec=WebSocket)
    ws2 = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, ws1)
    await manager.connect(room_id, ws2)

    payload = {"type": "test", "data": "hello"}
    callback = mock_pubsub_broker.subscribe.await_args.args[1]
    await callback(payload)

    ws1.send_json.assert_awaited_once_with(payload)
    ws2.send_json.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_connection_manager_when_socket_fails_should_remove_only_dead_socket(
    mock_pubsub_broker: AsyncMock,
) -> None:
    manager = ConnectionManager(broker=mock_pubsub_broker)
    room_id = uuid.uuid4()
    dead_ws = AsyncMock(spec=WebSocket)
    dead_ws.send_json.side_effect = RuntimeError("Broken pipe")
    live_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, dead_ws)
    await manager.connect(room_id, live_ws)

    callback = mock_pubsub_broker.subscribe.await_args.args[1]
    await callback({"type": "ping"})

    live_ws.send_json.assert_awaited_once()
    assert dead_ws not in manager._rooms[room_id]
    assert live_ws in manager._rooms[room_id]
