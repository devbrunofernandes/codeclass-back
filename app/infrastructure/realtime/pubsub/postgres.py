import asyncio
import json
import logging
from typing import Any

import asyncpg

from app.core.config import settings
from app.infrastructure.realtime.pubsub.base import MessageCallback, PubSubBroker

logger = logging.getLogger(__name__)


class PostgresListenNotifyBroker(PubSubBroker):
    """Provedor PostgreSQL LISTEN/NOTIFY via asyncpg para escalabilidade horizontal a Custo Zero."""

    def __init__(self, dsn: str | None = None) -> None:
        self._raw_dsn = dsn or settings.DATABASE_URL
        self._dsn = self._clean_dsn(self._raw_dsn)
        self._listener_conn: asyncpg.Connection | None = None
        self._pool: asyncpg.Pool | None = None
        self._listeners: dict[str, set[MessageCallback]] = {}
        self._is_connected: bool = False
        self._lock = asyncio.Lock()

    @staticmethod
    def _clean_dsn(dsn: str) -> str:
        """Converte DSN do SQLAlchemy asyncpg para formato nativo do driver asyncpg."""
        if dsn.startswith("postgresql+asyncpg://"):
            return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        if dsn.startswith("postgres+asyncpg://"):
            return dsn.replace("postgres+asyncpg://", "postgresql://", 1)
        return dsn

    async def connect(self) -> None:
        """Inicializa a conexão dedicada de escuta e o pool de publicação."""
        async with self._lock:
            if self._is_connected:
                return

            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            self._listener_conn = await asyncpg.connect(self._dsn)
            self._is_connected = True

    async def disconnect(self) -> None:
        """Encerra a conexão de escuta, cancela listeners e fecha o pool."""
        async with self._lock:
            if not self._is_connected:
                return

            if self._listener_conn and not self._listener_conn.is_closed():
                for channel in list(self._listeners.keys()):
                    try:
                        await self._listener_conn.remove_listener(
                            channel, self._raw_notification_handler
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Erro ao desregistrar listener do canal '%s': %s",
                            channel,
                            exc,
                        )
                try:
                    await self._listener_conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "Erro ao fechar conexão de listener do Postgres: %s", exc
                    )

            self._listener_conn = None

            if self._pool:
                try:
                    await self._pool.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Erro ao fechar pool asyncpg: %s", exc)
                self._pool = None

            self._listeners.clear()
            self._is_connected = False

    async def _raw_notification_handler(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Handler interno acionado pelo driver asyncpg ao receber um NOTIFY no canal."""
        try:
            data = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Payload JSON inválido recebido no canal '%s' via NOTIFY: %s",
                channel,
                exc,
            )
            return

        callbacks = list(self._listeners.get(channel, set()))
        if not callbacks:
            return

        async def _safe_call(cb: MessageCallback) -> None:
            try:
                await cb(data)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Erro ao executar callback no canal '%s': %s", channel, exc
                )

        await asyncio.gather(
            *(_safe_call(cb) for cb in callbacks),
            return_exceptions=True,
        )

    async def subscribe(self, channel: str, callback: MessageCallback) -> None:
        """Registra callback no canal, ativando LISTEN no PostgreSQL se for o 1º ouvinte."""
        if not self._is_connected or self._listener_conn is None:
            await self.connect()

        assert self._listener_conn is not None

        async with self._lock:
            if channel not in self._listeners:
                self._listeners[channel] = set()
                await self._listener_conn.add_listener(
                    channel, self._raw_notification_handler
                )
            self._listeners[channel].add(callback)

    async def unsubscribe(
        self, channel: str, callback: MessageCallback | None = None
    ) -> None:
        """Remove callback e executa UNLISTEN no PostgreSQL caso não restem ouvintes locais."""
        async with self._lock:
            if channel not in self._listeners:
                return

            if callback is None:
                del self._listeners[channel]
                if self._listener_conn and not self._listener_conn.is_closed():
                    await self._listener_conn.remove_listener(
                        channel, self._raw_notification_handler
                    )
            else:
                self._listeners[channel].discard(callback)
                if not self._listeners[channel]:
                    del self._listeners[channel]
                    if self._listener_conn and not self._listener_conn.is_closed():
                        await self._listener_conn.remove_listener(
                            channel, self._raw_notification_handler
                        )

    async def publish(self, channel: str, message: dict[str, Any]) -> None:
        """Emite pg_notify via pool para que todos os workers recebam o evento em tempo real."""
        if not self._is_connected or self._pool is None:
            await self.connect()

        assert self._pool is not None

        payload_str = json.dumps(message, default=str)
        if len(payload_str.encode("utf-8")) > 7500:
            logger.warning(
                "Payload excede o limite do PostgreSQL NOTIFY. Emitindo evento leve de refetch para '%s'",
                channel,
            )
            msg_id = (
                message.get("data", {}).get("id")
                if isinstance(message.get("data"), dict)
                else message.get("message_id")
            )
            fallback_payload = {
                "type": "message_refetch",
                "message_id": str(msg_id) if msg_id else None,
                "channel": channel,
            }
            payload_str = json.dumps(fallback_payload)

        await self._pool.execute("SELECT pg_notify($1, $2)", channel, payload_str)
