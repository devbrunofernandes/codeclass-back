import uuid
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocket

from app.infrastructure.realtime import ConnectionManager
from app.infrastructure.realtime.pubsub.in_memory import InMemoryPubSubBroker

# --- Testes Unitários de WebSocket ConnectionManager ---


@pytest.mark.asyncio
async def test_connection_manager_connect_and_disconnect() -> None:
    manager = ConnectionManager(broker=InMemoryPubSubBroker())
    room_id = uuid.uuid4()
    mock_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, mock_ws)
    assert room_id in manager._rooms
    assert mock_ws in manager._rooms[room_id]

    await manager.disconnect(room_id, mock_ws)
    assert room_id not in manager._rooms


@pytest.mark.asyncio
async def test_connection_manager_broadcast_success() -> None:
    manager = ConnectionManager(broker=InMemoryPubSubBroker())
    room_id = uuid.uuid4()
    ws1 = AsyncMock(spec=WebSocket)
    ws2 = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, ws1)
    await manager.connect(room_id, ws2)

    payload = {"type": "test", "data": "hello"}
    await manager.broadcast(room_id, payload)

    ws1.send_json.assert_awaited_once_with(payload)
    ws2.send_json.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_dead_socket_cleanup() -> None:
    manager = ConnectionManager(broker=InMemoryPubSubBroker())
    room_id = uuid.uuid4()
    dead_ws = AsyncMock(spec=WebSocket)
    dead_ws.send_json.side_effect = RuntimeError("Broken pipe")
    live_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, dead_ws)
    await manager.connect(room_id, live_ws)

    await manager.broadcast(room_id, {"type": "ping"})

    live_ws.send_json.assert_awaited_once()
    assert dead_ws not in manager._rooms[room_id]
    assert live_ws in manager._rooms[room_id]


# --- Testes Unitários de ChatService e Regras de Negócio ---
