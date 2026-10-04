import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocket

from app.core.config import settings
from app.infrastructure.realtime.connection_manager import ConnectionManager
from app.infrastructure.realtime.pubsub.postgres import (
    PostgresListenNotifyBroker,
)


@pytest.mark.asyncio
async def test_multi_worker_chat_pubsub_cross_node_delivery() -> None:
    """Valida entrega em tempo real entre nós distintos simulados via PostgreSQL LISTEN/NOTIFY."""
    classroom_id = uuid.uuid4()

    # Simula Worker 1 com broker dedicado conectado ao PostgreSQL real
    broker_worker_1 = PostgresListenNotifyBroker(dsn=settings.DATABASE_URL)
    await broker_worker_1.connect()
    worker_1 = ConnectionManager(broker=broker_worker_1)

    # Simula Worker 2 com broker dedicado conectado ao mesmo PostgreSQL real
    broker_worker_2 = PostgresListenNotifyBroker(dsn=settings.DATABASE_URL)
    await broker_worker_2.connect()
    worker_2 = ConnectionManager(broker=broker_worker_2)

    # Cliente A conecta-se ao Worker 1
    ws_client_a = AsyncMock(spec=WebSocket)
    await worker_1.connect(classroom_id, ws_client_a)

    # Cliente B conecta-se ao Worker 2
    ws_client_b = AsyncMock(spec=WebSocket)
    await worker_2.connect(classroom_id, ws_client_b)

    # Dá um breve respiro para que os comandos LISTEN sejam registrados no PostgreSQL
    await asyncio.sleep(0.05)

    # Worker 1 emite um broadcast de nova mensagem
    broadcast_payload = {
        "type": "new_message",
        "data": {
            "id": str(uuid.uuid4()),
            "classroom_id": str(classroom_id),
            "content": "Olá a todos os alunos via cluster multi-worker!",
            "sender": {"id": str(uuid.uuid4()), "role": "teacher"},
            "is_edited": False,
            "is_deleted": False,
        },
    }
    await worker_1.broadcast(classroom_id, broadcast_payload)

    # Aguarda a difusão da notificação do PostgreSQL
    await asyncio.sleep(0.15)

    # Asserção: Ambos os clientes (no Worker 1 e no Worker 2) devem ter recebido o payload exato
    ws_client_a.send_json.assert_awaited_once_with(broadcast_payload)
    ws_client_b.send_json.assert_awaited_once_with(broadcast_payload)

    # Limpeza e encerramento seguro
    await worker_1.disconnect(classroom_id, ws_client_a)
    await worker_2.disconnect(classroom_id, ws_client_b)
    await broker_worker_1.disconnect()
    await broker_worker_2.disconnect()
