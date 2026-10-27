from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictException
from app.models.classroom import Classroom
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.services.classroom_service import classroom_service


@pytest.mark.asyncio
async def test_enroll_batch_when_concurrent_conflict_should_rollback():
    student_id = uuid4()
    classroom = Classroom(
        id=uuid4(), organization_id=uuid4(), teacher_id=uuid4(), name="Turma"
    )
    user = User(id=student_id, full_name="Aluno", email="aluno@example.com")
    member = OrganizationMember(
        user_id=student_id,
        organization_id=classroom.organization_id,
        role=OrgRole.STUDENT,
        is_active=True,
        user=user,
    )
    members = MagicMock()
    members.scalars.return_value.all.return_value = [member]
    enrolled = MagicMock()
    enrolled.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[members, enrolled])
    db.flush = AsyncMock(side_effect=IntegrityError("insert", {}, Exception()))
    db.rollback = AsyncMock()
    db.commit = AsyncMock()
    with pytest.raises(ConflictException):
        await classroom_service.enroll_students_batch(classroom, [student_id], db)
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
