import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AppException, ConflictException
from app.models.enums import OrgRole
from app.schemas.organization import OrganizationMemberCreate
from app.services.auth_service import AuthError, auth_service
from app.services.member_service import MemberService


@pytest.fixture
def member_svc() -> MemberService:
    return MemberService()


@pytest.mark.asyncio
async def test_add_member_when_email_already_exists_raises_conflict(
    member_svc: MemberService,
) -> None:
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: MagicMock())
    current_member = MagicMock(role=OrgRole.OWNER)
    req = OrganizationMemberCreate(
        email="existing@example.com",
        full_name="Existing User",
        password="password123",
        role=OrgRole.TEACHER,
    )

    with pytest.raises(ConflictException, match="Já existe um usuário com este e-mail"):
        await member_svc.add_member(uuid.uuid4(), req, current_member, mock_db)


@pytest.mark.asyncio
async def test_create_member_compensatory_rollback_on_integrity_error(
    member_svc: MemberService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "test@org.com", "full_name": "Test"}
        ),
    )
    mock_delete = AsyncMock()
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    # Mock da sessão do banco
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = IntegrityError(
        "duplicate", orig=MagicMock(), params={}
    )

    current_member = MagicMock(role=OrgRole.OWNER)
    req = OrganizationMemberCreate(
        email="test@org.com",
        full_name="Test",
        password="password123",
        role=OrgRole.TEACHER,
    )

    with pytest.raises(ConflictException, match="Conflito ao registrar membro"):
        await member_svc.add_member(org_id, req, current_member, mock_db)

    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_member_compensatory_rollback_handles_auth_cleanup_error(
    member_svc: MemberService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "test@org.com", "full_name": "Test"}
        ),
    )
    mock_delete = AsyncMock(side_effect=AuthError("Auth down", status_code=500))
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = IntegrityError(
        "duplicate", orig=MagicMock(), params={}
    )

    current_member = MagicMock(role=OrgRole.OWNER)
    req = OrganizationMemberCreate(
        email="test@org.com",
        full_name="Test",
        password="password123",
        role=OrgRole.TEACHER,
    )

    with pytest.raises(ConflictException):
        await member_svc.add_member(org_id, req, current_member, mock_db)

    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_member_compensatory_rollback_on_generic_exception(
    member_svc: MemberService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "test@org.com", "full_name": "Test"}
        ),
    )
    mock_delete = AsyncMock()
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = RuntimeError("Database connection crashed")

    current_member = MagicMock(role=OrgRole.OWNER)
    req = OrganizationMemberCreate(
        email="test@org.com",
        full_name="Test",
        password="password123",
        role=OrgRole.STUDENT,
    )

    with pytest.raises(AppException) as exc_info:
        await member_svc.add_member(org_id, req, current_member, mock_db)

    assert exc_info.value.status_code == 500
    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_member_compensatory_rollback_on_generic_exception_handles_auth_cleanup_error(
    member_svc: MemberService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    org_id = uuid.uuid4()

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "test@org.com", "full_name": "Test"}
        ),
    )
    mock_delete = AsyncMock(
        side_effect=AuthError("Auth cleanup failed", status_code=500)
    )
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = RuntimeError("Database crashed")

    current_member = MagicMock(role=OrgRole.OWNER)
    req = OrganizationMemberCreate(
        email="test@org.com",
        full_name="Test",
        password="password123",
        role=OrgRole.STUDENT,
    )

    with pytest.raises(AppException) as exc_info:
        await member_svc.add_member(org_id, req, current_member, mock_db)

    assert exc_info.value.status_code == 500
    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)
