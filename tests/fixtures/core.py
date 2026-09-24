import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

import app.models
from app.core.config import settings
from app.core.database import Base, async_session_maker, engine
from app.main import app


@pytest.fixture(autouse=True)
async def cleanup_database() -> AsyncGenerator[None]:
    """Limpa todas as tabelas antes e depois de cada teste para garantir isolamento estrito."""

    async def _clean() -> None:
        async with async_session_maker() as session:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(table.delete())
            await session.commit()

    await _clean()
    yield
    await _clean()
    await engine.dispose()


@pytest.fixture
def create_access_token() -> Callable[
    [uuid.UUID | str, str, str, timedelta | None], str
]:
    """Helper para emissão de JWT sintético compatível com GoTrue do Supabase."""

    def _create_token(
        user_id: uuid.UUID | str,
        email: str = "test@example.com",
        full_name: str = "Test User",
        expires_delta: timedelta | None = None,
    ) -> str:
        now = datetime.now(UTC)
        expire = now + (expires_delta or timedelta(hours=1))
        payload = {
            "sub": str(user_id),
            "email": email,
            "role": "authenticated",
            "user_metadata": {"full_name": full_name},
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
        secret = (
            settings.SUPABASE_JWT_SECRET
            or "super-secret-jwt-token-with-at-least-32-characters-long"
        )
        return jwt.encode(payload, secret, algorithm="HS256")

    return _create_token


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient]:
    """Cliente HTTP assíncrono para testes de controladores e endpoints."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Sessão assíncrona do banco de dados para os testes."""
    async with async_session_maker() as session:
        yield session
