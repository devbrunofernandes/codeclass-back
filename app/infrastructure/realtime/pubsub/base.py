from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

MessageCallback = Callable[[dict[str, Any]], Awaitable[None]]


class PubSubBroker(ABC):
    """Interface abstrata (Strategy Pattern) para mensageria e Pub/Sub em tempo real."""

    @abstractmethod
    async def connect(self) -> None:
        """Inicializa conexões ou recursos do broker."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Encerra conexões e recursos do broker."""

    @abstractmethod
    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Publica um payload JSON no canal informado."""

    @abstractmethod
    async def subscribe(self, channel: str, callback: MessageCallback) -> None:
        """Registra um callback assíncrono para receber mensagens no canal."""

    @abstractmethod
    async def unsubscribe(
        self, channel: str, callback: MessageCallback | None = None
    ) -> None:
        """Remove a inscrição do callback no canal (ou todos do canal se callback for None)."""
