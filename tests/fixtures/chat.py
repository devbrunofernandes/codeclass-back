import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ClassroomMessage


@pytest.fixture
def create_classroom_message(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[ClassroomMessage]]:
    """Factory para instanciar mensagens no chat da sala com suporte a datas retroativas."""

    async def _create(
        classroom_id: uuid.UUID,
        sender_id: uuid.UUID,
        content: str = "Olá turma!",
        is_edited: bool = False,
        is_deleted: bool = False,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        **extra: Any,
    ) -> ClassroomMessage:
        now = datetime.now(UTC)
        msg = ClassroomMessage(
            id=uuid.uuid4(),
            classroom_id=classroom_id,
            sender_id=sender_id,
            content=content,
            is_edited=is_edited,
            is_deleted=is_deleted,
            created_at=created_at or now,
            updated_at=updated_at or created_at or now,
            **extra,
        )
        db_session.add(msg)
        await db_session.commit()
        await db_session.refresh(msg)
        return msg

    return _create
