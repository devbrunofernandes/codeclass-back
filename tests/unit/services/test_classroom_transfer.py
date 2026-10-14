from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
)
from app.models.classroom import Classroom
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.services.classroom_service import classroom_service


def _query_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_transfer_classroom_teacher_when_owner_assigns_teacher_should_commit() -> (
    None
):
    classroom_id = uuid4()
    organization_id = uuid4()
    owner_id = uuid4()
    teacher_id = uuid4()
    classroom = Classroom(
        id=classroom_id,
        organization_id=organization_id,
        teacher_id=uuid4(),
        name="Original",
    )
    owner = OrganizationMember(
        organization_id=organization_id,
        user_id=owner_id,
        role=OrgRole.OWNER,
        is_active=True,
    )
    teacher = OrganizationMember(
        organization_id=organization_id,
        user_id=teacher_id,
        role=OrgRole.TEACHER,
        is_active=True,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _query_result(classroom),
            _query_result(owner),
            _query_result(teacher),
        ]
    )
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.rollback = AsyncMock()

    updated = await classroom_service.transfer_teacher(
        classroom, teacher_id, owner_id, db
    )

    assert updated.teacher_id == teacher_id
    assert updated.name == "Original"
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_transfer_classroom_teacher_when_actor_is_teacher_should_rollback() -> (
    None
):
    classroom_id = uuid4()
    organization_id = uuid4()
    teacher_id = uuid4()
    replacement_id = uuid4()
    classroom = Classroom(
        id=classroom_id,
        organization_id=organization_id,
        teacher_id=teacher_id,
        name="Original",
    )
    actor = OrganizationMember(
        organization_id=organization_id,
        user_id=teacher_id,
        role=OrgRole.TEACHER,
        is_active=True,
    )
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[_query_result(classroom), _query_result(actor)])
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    with pytest.raises(ForbiddenException):
        await classroom_service.transfer_teacher(
            classroom, replacement_id, teacher_id, db
        )

    assert classroom.name == "Original"
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_transfer_classroom_teacher_when_integrity_conflict_should_return_409() -> (
    None
):
    from sqlalchemy.exc import IntegrityError

    classroom = Classroom(
        id=uuid4(),
        organization_id=uuid4(),
        teacher_id=uuid4(),
        name="Original",
    )
    owner_id = uuid4()
    teacher_id = uuid4()
    owner = OrganizationMember(
        organization_id=classroom.organization_id,
        user_id=owner_id,
        role=OrgRole.OWNER,
        is_active=True,
    )
    teacher = OrganizationMember(
        organization_id=classroom.organization_id,
        user_id=teacher_id,
        role=OrgRole.TEACHER,
        is_active=True,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _query_result(classroom),
            _query_result(owner),
            _query_result(teacher),
        ]
    )
    db.commit = AsyncMock(side_effect=IntegrityError("UPDATE", {}, Exception()))
    db.rollback = AsyncMock()

    with pytest.raises(ConflictException) as exc:
        await classroom_service.transfer_teacher(classroom, teacher_id, owner_id, db)

    assert exc.value.status_code == 409
    db.rollback.assert_awaited_once()
