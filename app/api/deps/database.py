from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Injeta a sessão de banco de dados assíncrona para a requisição HTTP."""
    async with async_session_maker() as session:
        yield session
