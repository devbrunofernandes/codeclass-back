"""Seleção, configuração e recursos dos testes com serviços reais."""

import asyncio
import socket
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest

from tests.fixtures.providers import required_provider_settings

SERVICES = {"ai", "runner", "storage", "auth", "chat"}


def validate_live_settings(service: str, config: Any) -> None:
    if service not in SERVICES:
        raise pytest.UsageError(f"Serviço live desconhecido: {service}")
    required = ("DATABASE_URL", *required_provider_settings(service, config))
    missing = [name for name in required if not getattr(config, name, "")]
    if missing:
        raise pytest.UsageError(
            f"Configuração live ({service}) ausente: {', '.join(missing)}"
        )


def live_service(node: pytest.Item) -> str | None:
    marker = node.get_closest_marker("live")
    if marker is None:
        return None
    if len(marker.args) != 1 or marker.args[0] not in SERVICES:
        raise pytest.UsageError("Use @pytest.mark.live('ai|runner|storage|auth|chat')")
    return str(marker.args[0])


def pytest_collection_finish(session: pytest.Session) -> None:
    for item in session.items:
        service = live_service(item)
        if service is not None:
            from app.core.config import settings

            validate_live_settings(service, settings)


@pytest.fixture
async def live_storage_material(classroom_with_student, tenant):
    """Registra a limpeza antes do upload, inclusive se o teste falhar."""
    from app.services.storage_service import storage_service

    name = f"live-{uuid4().hex}.txt"
    try:
        yield name
    finally:
        await storage_service.delete_classroom_material(
            tenant.org.id, classroom_with_student.id, name
        )


@pytest.fixture
async def live_chat_server(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[str]:
    """Servidor TCP efêmero com a estratégia de broker configurada."""
    import uvicorn

    from app.api.v1 import chat
    from app.infrastructure.realtime.connection_manager import ConnectionManager
    from app.infrastructure.realtime.pubsub.factory import get_pubsub_broker
    from app.main import app
    from app.services import chat_service

    manager = ConnectionManager(broker=get_pubsub_broker())
    monkeypatch.setattr(chat, "connection_manager", manager)
    monkeypatch.setattr(chat_service, "connection_manager", manager)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", lifespan="off")
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Servidor live encerrou antes de iniciar")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(task, timeout=10)
            finally:
                await manager.shutdown()
