from app.core.config import settings
from app.infrastructure.realtime.pubsub.base import PubSubBroker


def get_pubsub_broker(provider_name: str | None = None) -> PubSubBroker:
    """Factory para instanciar o provedor de Pub/Sub ativo de acordo com as configurações."""
    name = (provider_name or settings.PUBSUB_BROKER or "in_memory").lower()

    if name == "in_memory":
        from app.infrastructure.realtime.pubsub.in_memory import InMemoryPubSubBroker

        return InMemoryPubSubBroker()

    if name == "postgres":
        from app.infrastructure.realtime.pubsub.postgres import (
            PostgresListenNotifyBroker,
        )

        return PostgresListenNotifyBroker()

    raise ValueError(f"Provedor de Pub/Sub não suportado: '{name}'")
