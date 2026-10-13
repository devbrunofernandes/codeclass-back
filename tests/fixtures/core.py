from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def cleanup_database() -> AsyncGenerator[None]:
    """Limpa todas as tabelas antes e depois de cada teste para garantir isolamento estrito."""

    import app.models  # noqa: F401
    from app.core.database import Base, async_session_maker, engine

    async def _clean() -> None:
        async with async_session_maker() as session:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(table.delete())
            await session.commit()

    try:
        await _clean()
        yield
    finally:
        try:
            await _clean()
        finally:
            await engine.dispose()


@pytest.fixture
async def async_client(cleanup_database: None) -> AsyncGenerator[AsyncClient]:
    """Cliente HTTP assíncrono para testes de controladores e endpoints."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
async def db_session(cleanup_database: None) -> AsyncGenerator[AsyncSession]:
    """Sessão assíncrona do banco de dados para os testes."""
    from app.core.database import async_session_maker

    async with async_session_maker() as session:
        yield session
