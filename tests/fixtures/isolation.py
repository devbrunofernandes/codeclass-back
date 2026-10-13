"""Proteções reutilizáveis dos testes sem infraestrutura externa."""

import socket
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_connection(*args: object, **kwargs: object) -> None:
        raise AssertionError("Teste unitário tentou acessar a rede")

    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_connection)
    monkeypatch.setattr(socket, "create_connection", reject_connection)


@pytest.fixture
def mocked_blocking_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executa callbacks de SDKs mockados e arquivos em memória sem threads."""

    async def run_mocked[T](func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        return func(*args)

    monkeypatch.setattr("anyio.to_thread.run_sync", run_mocked)


def collect_fixture_scopes(paths: list[str], *, domain_only: bool = False) -> None:
    """Audita a coleta real em um processo novo, sem executar fixtures de banco."""
    import subprocess
    import sys
    from pathlib import Path

    script = """
import sys
import pytest

class ScopeProbe:
    def pytest_collection_finish(self, session):
        for item in session.items:
            parts = item.path.parts
            if "unit" in parts:
                assert "cleanup_database" not in item.fixturenames, item.nodeid
                assert "db_session" not in item.fixturenames, item.nodeid
                assert "mock_ai_service" not in item.fixturenames, item.nodeid
                assert "override_runner_provider" not in item.fixturenames, item.nodeid
            elif "api" in parts or "integration" in parts:
                assert "cleanup_database" in item.fixturenames, item.nodeid
        if sys.argv[1] == "domain":
            for module in (
                "app.main", "app.services.ai_service",
                "app.services.runner_service", "app.services.storage_service",
                "app.infrastructure.auth.supabase_auth",
            ):
                assert module not in sys.modules, module

raise SystemExit(pytest.main(["--collect-only", "-q", *sys.argv[2:]], plugins=[ScopeProbe()]))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, "domain" if domain_only else "mixed", *paths],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def cleanup_session_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncMock, AsyncMock]:
    """Sessão mockada para verificar o ciclo de limpeza sem PostgreSQL."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core import database

    session = AsyncMock(spec=AsyncSession)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "async_session_maker", lambda: context)
    dispose = AsyncMock()
    monkeypatch.setattr(database, "engine", MagicMock(dispose=dispose))
    return session, dispose
