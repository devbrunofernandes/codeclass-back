import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps.resolvers import (
    _build_classroom_context,
    authenticate_classroom_connection,
    get_assignment_context,
    get_classroom_context,
    get_submission_context,
)
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.models.classroom import Classroom
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember


class TestContextResolvers:
    @pytest.mark.asyncio
    async def test_build_classroom_context_tenant_mismatch_raises_forbidden(self):
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()

        classroom = Classroom(
            id=uuid.uuid4(), organization_id=org_id, teacher_id=uuid.uuid4()
        )
        member = OrganizationMember(
            user_id=uuid.uuid4(),
            organization_id=other_org_id,
            role=OrgRole.STUDENT,
        )
        mock_db = AsyncMock()

        with pytest.raises(ForbiddenException) as exc:
            await _build_classroom_context(
                classroom=classroom, current_member=member, db=mock_db
            )
        assert "outra organização" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_get_classroom_context_not_found_raises_404(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        member = OrganizationMember(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
        with pytest.raises(NotFoundException):
            await get_classroom_context(
                classroom_id=uuid.uuid4(), current_member=member, db=mock_db
            )

    @pytest.mark.asyncio
    async def test_get_assignment_context_not_found_raises_404(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        member = OrganizationMember(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
        with pytest.raises(NotFoundException):
            await get_assignment_context(
                assignment_id=uuid.uuid4(), current_member=member, db=mock_db
            )

    @pytest.mark.asyncio
    async def test_get_submission_context_not_found_raises_404(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        member = OrganizationMember(organization_id=uuid.uuid4(), user_id=uuid.uuid4())
        with pytest.raises(NotFoundException):
            await get_submission_context(
                submission_id=uuid.uuid4(), current_member=member, db=mock_db
            )

    @pytest.mark.asyncio
    async def test_authenticate_classroom_connection_when_token_none_should_raise_unauthorized(
        self,
    ):
        mock_db = AsyncMock()
        with pytest.raises(UnauthorizedException) as exc:
            await authenticate_classroom_connection(
                classroom_id=uuid.uuid4(), token=None, db=mock_db
            )
        assert "não fornecido" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_authenticate_classroom_connection_when_classroom_not_found_should_raise_404(
        self, monkeypatch
    ):
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_mock = MagicMock(id=user_id)
        member_mock = MagicMock(user_id=user_id, organization_id=org_id, is_active=True)

        monkeypatch.setattr(
            "app.api.deps.resolvers.get_user_from_token",
            AsyncMock(return_value=user_mock),
        )
        monkeypatch.setattr(
            "app.api.deps.resolvers.get_active_member_by_user_id",
            AsyncMock(return_value=member_mock),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(NotFoundException):
            await authenticate_classroom_connection(
                classroom_id=uuid.uuid4(), token="valid_jwt", db=mock_db
            )

    @pytest.mark.asyncio
    async def test_authenticate_classroom_connection_when_not_permitted_should_raise_forbidden(
        self, monkeypatch
    ):
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_mock = MagicMock(id=user_id)
        member = OrganizationMember(
            user_id=user_id,
            organization_id=org_id,
            role=OrgRole.STUDENT,
            is_active=True,
        )

        monkeypatch.setattr(
            "app.api.deps.resolvers.get_user_from_token",
            AsyncMock(return_value=user_mock),
        )
        monkeypatch.setattr(
            "app.api.deps.resolvers.get_active_member_by_user_id",
            AsyncMock(return_value=member),
        )

        classroom = Classroom(
            id=uuid.uuid4(),
            organization_id=org_id,
            teacher_id=uuid.uuid4(),  # Outro professor
        )

        mock_db = AsyncMock()
        # Primeiro execute: Classroom; Segundo execute: ClassroomStudent (retorna None)
        class_res = MagicMock()
        class_res.scalar_one_or_none.return_value = classroom
        student_res = MagicMock()
        student_res.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [class_res, student_res]

        with pytest.raises(ForbiddenException) as exc:
            await authenticate_classroom_connection(
                classroom_id=classroom.id, token="valid_jwt", db=mock_db
            )
        assert "não possui permissão" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_authenticate_classroom_connection_when_teacher_should_succeed(
        self, monkeypatch
    ):
        user_id = uuid.uuid4()
        org_id = uuid.uuid4()
        user_mock = MagicMock(id=user_id)
        member = OrganizationMember(
            user_id=user_id,
            organization_id=org_id,
            role=OrgRole.TEACHER,
            is_active=True,
        )

        monkeypatch.setattr(
            "app.api.deps.resolvers.get_user_from_token",
            AsyncMock(return_value=user_mock),
        )
        monkeypatch.setattr(
            "app.api.deps.resolvers.get_active_member_by_user_id",
            AsyncMock(return_value=member),
        )

        classroom = Classroom(
            id=uuid.uuid4(),
            organization_id=org_id,
            teacher_id=user_id,
        )

        mock_db = AsyncMock()
        class_res = MagicMock()
        class_res.scalar_one_or_none.return_value = classroom
        student_res = MagicMock()
        student_res.scalar_one_or_none.return_value = None
        mock_db.execute.side_effect = [class_res, student_res]

        context = await authenticate_classroom_connection(
            classroom_id=classroom.id, token="valid_jwt", db=mock_db
        )
        assert context.classroom == classroom
        assert context.can_view is True
        assert context.is_teacher_of_class is True
