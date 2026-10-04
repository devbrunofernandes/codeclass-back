import asyncio
import uuid
from typing import Any

from starlette.websockets import WebSocket

from app.infrastructure.realtime.pubsub.base import MessageCallback, PubSubBroker
from app.infrastructure.realtime.pubsub.factory import get_pubsub_broker


class ConnectionManager:
    """Gerenciador assíncrono para conexões WebSocket por turma com suporte a Pub/Sub distribuído."""

    def __init__(self, broker: PubSubBroker | None = None) -> None:
        self._rooms: dict[uuid.UUID, set[WebSocket]] = {}
        self._broker: PubSubBroker = (
            broker if broker is not None else get_pubsub_broker()
        )
        self._room_callbacks: dict[uuid.UUID, MessageCallback] = {}

    @property
    def broker(self) -> PubSubBroker:
        """Retorna o broker de mensageria ativo do ConnectionManager."""
        return self._broker

    async def shutdown(self) -> None:
        """Encerra com segurança todas as conexões e desconecta o broker."""
        self._rooms.clear()
        self._room_callbacks.clear()
        await self._broker.disconnect()

    @staticmethod
    def _channel_for(classroom_id: uuid.UUID) -> str:
        return f"classroom:{classroom_id}"

    async def connect(self, classroom_id: uuid.UUID, websocket: WebSocket) -> None:
        """Registra a conexão WebSocket ativa no canal da turma e inscreve no broker se for a 1ª."""
        if classroom_id not in self._rooms:
            self._rooms[classroom_id] = set()

        self._rooms[classroom_id].add(websocket)

        if classroom_id not in self._room_callbacks:

            async def _room_handler(msg: dict[str, Any]) -> None:
                await self._send_to_local_room(classroom_id, msg)

            self._room_callbacks[classroom_id] = _room_handler
            channel = self._channel_for(classroom_id)
            await self._broker.subscribe(channel, _room_handler)

    async def disconnect(self, classroom_id: uuid.UUID, websocket: WebSocket) -> None:
        """Remove a conexão WebSocket do canal e limpa salas vazias e inscrição no broker."""
        if classroom_id in self._rooms:
            self._rooms[classroom_id].discard(websocket)
            if not self._rooms[classroom_id]:
                del self._rooms[classroom_id]
                cb = self._room_callbacks.pop(classroom_id, None)
                if cb is not None:
                    channel = self._channel_for(classroom_id)
                    await self._broker.unsubscribe(channel, cb)

    async def _send_safe(
        self, classroom_id: uuid.UUID, ws: WebSocket, message: dict[str, Any]
    ) -> None:
        try:
            await ws.send_json(message)
        except Exception:  # noqa: BLE001
            # Conexão perdida, socket fechado ou falha de I/O
            await self.disconnect(classroom_id, ws)

    async def _send_to_local_room(
        self, classroom_id: uuid.UUID, message: dict[str, Any]
    ) -> None:
        """Distribui payload JSON concorrentemente para todos os WebSockets locais da turma."""
        if classroom_id not in self._rooms:
            return

        active_sockets = list(self._rooms[classroom_id])
        if active_sockets:
            await asyncio.gather(
                *(self._send_safe(classroom_id, ws, message) for ws in active_sockets),
                return_exceptions=True,
            )

    async def broadcast(self, classroom_id: uuid.UUID, message: dict[str, Any]) -> None:
        """Publica mensagem no broker de Pub/Sub para difusão entre todos os nós e clientes."""
        channel = self._channel_for(classroom_id)
        await self._broker.publish(channel, message)


connection_manager = ConnectionManager()
