import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps.resolvers import (
    _build_classroom_context,
    get_assignment_context,
    get_classroom_context,
    get_submission_context,
)
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
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
