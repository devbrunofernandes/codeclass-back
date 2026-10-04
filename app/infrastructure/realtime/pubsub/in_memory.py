import asyncio
import logging
from typing import Any

from app.infrastructure.realtime.pubsub.base import MessageCallback, PubSubBroker

logger = logging.getLogger(__name__)


class InMemoryPubSubBroker(PubSubBroker):
    """Provedor in-memory assíncrono de Pub/Sub para testes e desenvolvimento local."""

    def __init__(self) -> None:
        self._listeners: dict[str, set[MessageCallback]] = {}
        self._is_connected: bool = False

    async def connect(self) -> None:
        """Marca o broker como conectado."""
        self._is_connected = True

    async def disconnect(self) -> None:
        """Limpa inscrições e desconecta o broker."""
        self._listeners.clear()
        self._is_connected = False

    async def subscribe(self, channel: str, callback: MessageCallback) -> None:
        """Registra um callback assíncrono no canal em memória."""
        if channel not in self._listeners:
            self._listeners[channel] = set()
        self._listeners[channel].add(callback)

    async def unsubscribe(
        self, channel: str, callback: MessageCallback | None = None
    ) -> None:
        """Remove callback do canal (ou o canal inteiro se callback for None)."""
        if channel not in self._listeners:
            return

        if callback is None:
            del self._listeners[channel]
        else:
            self._listeners[channel].discard(callback)
            if not self._listeners[channel]:
                del self._listeners[channel]

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Executa todos os callbacks inscritos para o canal de forma concorrente e segura."""
        if channel not in self._listeners:
            return

        callbacks = list(self._listeners[channel])
        if not callbacks:
            return

        async def _safe_call(cb: MessageCallback) -> None:
            try:
                await cb(message)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Erro ao executar callback no canal '%s': %s", channel, exc
                )

        await asyncio.gather(
            *(_safe_call(cb) for cb in callbacks),
            return_exceptions=True,
        )
