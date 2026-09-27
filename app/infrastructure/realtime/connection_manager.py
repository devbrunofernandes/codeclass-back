import asyncio
import uuid
from typing import Any

from starlette.websockets import WebSocket


class ConnectionManager:
    """Gerenciador in-memory thread-safe e assíncrono para conexões WebSocket por turma."""

    def __init__(self) -> None:
        self._rooms: dict[uuid.UUID, set[WebSocket]] = {}

    async def connect(self, classroom_id: uuid.UUID, websocket: WebSocket) -> None:
        """Registra a conexão WebSocket ativa no canal da turma."""
        if classroom_id not in self._rooms:
            self._rooms[classroom_id] = set()
        self._rooms[classroom_id].add(websocket)

    def disconnect(self, classroom_id: uuid.UUID, websocket: WebSocket) -> None:
        """Remove a conexão WebSocket do canal e limpa salas vazias."""
        if classroom_id in self._rooms:
            self._rooms[classroom_id].discard(websocket)
            if not self._rooms[classroom_id]:
                del self._rooms[classroom_id]

    async def _send_safe(
        self, classroom_id: uuid.UUID, ws: WebSocket, message: dict[str, Any]
    ) -> None:
        try:
            await ws.send_json(message)
        except Exception:  # noqa: BLE001
            # Conexão perdida, socket fechado ou falha de I/O
            self.disconnect(classroom_id, ws)

    async def broadcast(self, classroom_id: uuid.UUID, message: dict[str, Any]) -> None:
        """Distribui payload JSON concorrentemente para todas as conexões ativas na sala com descarte seguro."""
        if classroom_id not in self._rooms:
            return

        active_sockets = list(self._rooms[classroom_id])
        if active_sockets:
            await asyncio.gather(
                *(self._send_safe(classroom_id, ws, message) for ws in active_sockets),
                return_exceptions=True,
            )


connection_manager = ConnectionManager()
