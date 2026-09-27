import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    AppException,
    AuthError,
    ConflictException,
    NotFoundException,
)
from app.infrastructure.auth import auth_service
from app.models.enums import OrgRole
from app.models.organization import Organization
from app.schemas.organization import (
    OrganizationRegisterRequest,
    OrganizationUpdateRequest,
    TransferOwnershipRequest,
)
from app.schemas.user import UserCreate
from app.services.organization_service import OrganizationService


@pytest.fixture
def org_svc() -> OrganizationService:
    return OrganizationService()


@pytest.mark.asyncio
async def test_register_organization_duplicate_email_raises_409(
    org_svc: OrganizationService,
) -> None:
    mock_db = AsyncMock()
    # 1. slug check -> None (livre)
    # 2. email check -> User (já existe)
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: None),
        MagicMock(scalar_one_or_none=lambda: MagicMock()),
    ]

    req = OrganizationRegisterRequest(
        name="Org Test",
        slug="org-test",
        owner=UserCreate(
            email="existing@org.com",
            full_name="Owner",
            password="password123",
        ),
    )

    with pytest.raises(
        ConflictException, match="Já existe um usuário.*com este e-mail"
    ):
        await org_svc.register_organization(req, mock_db)


# --- create_organization rollbacks compensatórios ---


@pytest.mark.asyncio
async def test_create_organization_compensatory_rollback_on_integrity_error(
    org_svc: OrganizationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "owner@org.com", "full_name": "Owner"}
        ),
    )
    mock_delete = AsyncMock()
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    # Retorna None para a checagem de slug inicial
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = IntegrityError(
        "duplicate", orig=MagicMock(), params={}
    )

    req = OrganizationRegisterRequest(
        name="Org Test",
        slug="org-test",
        owner=UserCreate(
            email="owner@org.com",
            full_name="Owner",
            password="password123",
        ),
    )

    with pytest.raises(ConflictException, match="Organização com este slug"):
        await org_svc.register_organization(req, mock_db)

    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_organization_compensatory_rollback_handles_auth_cleanup_error(
    org_svc: OrganizationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "owner@org.com", "full_name": "Owner"}
        ),
    )
    mock_delete = AsyncMock(side_effect=AuthError("Auth unavailable", status_code=500))
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = IntegrityError(
        "duplicate", orig=MagicMock(), params={}
    )

    req = OrganizationRegisterRequest(
        name="Org Test",
        slug="org-test",
        owner=UserCreate(
            email="owner@org.com",
            full_name="Owner",
            password="password123",
        ),
    )

    with pytest.raises(ConflictException):
        await org_svc.register_organization(req, mock_db)

    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_organization_compensatory_rollback_on_generic_exception(
    org_svc: OrganizationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "owner@org.com", "full_name": "Owner"}
        ),
    )
    mock_delete = AsyncMock()
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = RuntimeError("Fatal DB failure")

    req = OrganizationRegisterRequest(
        name="Org Test",
        slug="org-test",
        owner=UserCreate(
            email="owner@org.com",
            full_name="Owner",
            password="password123",
        ),
    )

    with pytest.raises(AppException) as exc_info:
        await org_svc.register_organization(req, mock_db)

    assert exc_info.value.status_code == 500
    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


@pytest.mark.asyncio
async def test_create_organization_compensatory_rollback_generic_exception_handles_auth_cleanup_error(
    org_svc: OrganizationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": user_id, "email": "owner@org.com", "full_name": "Owner"}
        ),
    )
    mock_delete = AsyncMock(side_effect=AuthError("Auth unavailable", status_code=500))
    monkeypatch.setattr(auth_service, "delete_auth_user", mock_delete)

    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)
    mock_db.commit.side_effect = RuntimeError("Fatal DB failure")

    req = OrganizationRegisterRequest(
        name="Org Test",
        slug="org-test",
        owner=UserCreate(
            email="owner@org.com",
            full_name="Owner",
            password="password123",
        ),
    )

    with pytest.raises(AppException) as exc_info:
        await org_svc.register_organization(req, mock_db)

    assert exc_info.value.status_code == 500
    mock_db.rollback.assert_called_once()
    mock_delete.assert_awaited_once_with(user_id)


# --- get_organization, update_organization & delete_organization not found ---


@pytest.mark.asyncio
async def test_get_organization_not_found_raises_404(
    org_svc: OrganizationService,
) -> None:
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    with pytest.raises(NotFoundException, match="Organização não encontrada."):
        await org_svc.get_organization(uuid.uuid4(), mock_db)


@pytest.mark.asyncio
async def test_update_organization_not_found_raises_404(
    org_svc: OrganizationService,
) -> None:
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    with pytest.raises(NotFoundException, match="Organização não encontrada."):
        await org_svc.update_organization(
            uuid.uuid4(), OrganizationUpdateRequest(name="New"), mock_db
        )


@pytest.mark.asyncio
async def test_update_organization_slug_conflict_raises_409(
    org_svc: OrganizationService,
) -> None:
    org_id = uuid.uuid4()
    mock_org = MagicMock(id=org_id, slug="old-slug")

    mock_db = AsyncMock()
    # Primeira chamada: encontra a organização atual
    # Segunda chamada: encontra outra organização com o mesmo slug desejado
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_org),
        MagicMock(scalar_one_or_none=lambda: MagicMock(id=uuid.uuid4())),
    ]

    req = OrganizationUpdateRequest(slug="new-slug")
    with pytest.raises(ConflictException, match="Este slug já está em uso"):
        await org_svc.update_organization(org_id, req, mock_db)


@pytest.mark.asyncio
async def test_update_organization_integrity_error_on_commit_raises_409(
    org_svc: OrganizationService,
) -> None:
    org_id = uuid.uuid4()
    mock_org = MagicMock(id=org_id, slug="old-slug")

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_org),
        MagicMock(scalar_one_or_none=lambda: None),
    ]
    mock_db.commit.side_effect = IntegrityError(
        "duplicate key", orig=MagicMock(), params={}
    )

    req = OrganizationUpdateRequest(slug="new-slug")
    with pytest.raises(ConflictException, match="Este slug já está em uso"):
        await org_svc.update_organization(org_id, req, mock_db)

    mock_db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_delete_organization_not_found_raises_404(
    org_svc: OrganizationService,
) -> None:
    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    with pytest.raises(NotFoundException, match="Organização não encontrada."):
        await org_svc.delete_organization(uuid.uuid4(), mock_db)


@pytest.mark.asyncio
async def test_transfer_ownership_organization_not_found_raises_404(
    org_svc: OrganizationService,
) -> None:
    mock_db = AsyncMock()
    target_member = MagicMock(is_active=True, role=OrgRole.ADMIN)

    # 1. target member ok
    # 2. org is None
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: target_member),
        MagicMock(scalar_one_or_none=lambda: None),
    ]

    current_member = MagicMock(role=OrgRole.OWNER)
    req = TransferOwnershipRequest(new_owner_id=uuid.uuid4())

    with pytest.raises(NotFoundException, match="Organização não encontrada."):
        await org_svc.transfer_ownership(uuid.uuid4(), req, current_member, mock_db)


@pytest.mark.asyncio
async def test_transfer_ownership_success(org_svc: OrganizationService) -> None:
    from datetime import UTC, datetime

    org_id = uuid.uuid4()
    old_owner_id = uuid.uuid4()
    new_owner_id = uuid.uuid4()

    current_member = MagicMock(role=OrgRole.OWNER, user_id=old_owner_id)
    target_member = MagicMock(role=OrgRole.ADMIN, user_id=new_owner_id, is_active=True)

    mock_org = Organization(
        id=org_id,
        name="Org Test",
        slug="org-test",
        owner_id=old_owner_id,
        created_at=datetime.now(UTC),
    )

    mock_db = AsyncMock()
    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: target_member),
        MagicMock(scalar_one_or_none=lambda: mock_org),
    ]

    req = TransferOwnershipRequest(new_owner_id=new_owner_id)
    res = await org_svc.transfer_ownership(org_id, req, current_member, mock_db)

    assert current_member.role == OrgRole.ADMIN
    assert target_member.role == OrgRole.OWNER
    assert mock_org.owner_id == new_owner_id
    assert res.owner_id == new_owner_id
    mock_db.commit.assert_called_once()
