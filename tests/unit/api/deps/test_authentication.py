import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.deps.authentication import (
    get_current_active_member,
    get_current_user,
)
from app.core.exceptions import (
    ForbiddenException,
    UnauthorizedException,
)
from app.infrastructure.auth import auth_service
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User


class TestAuthenticationDependencies:
    @pytest.mark.asyncio
    async def test_get_current_user_when_token_valid_and_user_exists(self, monkeypatch):
        user_id = uuid.uuid4()
        monkeypatch.setattr(
            auth_service,
            "verify_jwt_token",
            AsyncMock(return_value={"sub": str(user_id)}),
        )

        user = User(id=user_id, email="test@test.com", full_name="User Test")
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = user
        mock_db.execute.return_value = mock_result

        credentials = MagicMock()
        credentials.credentials = "valid_token"

        result = await get_current_user(credentials=credentials, db=mock_db)
        assert result == user

    @pytest.mark.asyncio
    async def test_get_current_user_when_token_lacks_sub_should_raise_unauthorized(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            auth_service,
            "verify_jwt_token",
            AsyncMock(return_value={}),
        )

        credentials = MagicMock()
        credentials.credentials = "token_without_sub"
        mock_db = AsyncMock()

        with pytest.raises(UnauthorizedException) as exc:
            await get_current_user(credentials=credentials, db=mock_db)
        assert "sujeito não encontrado" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_get_current_user_when_sub_invalid_uuid_should_raise_unauthorized(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            auth_service,
            "verify_jwt_token",
            AsyncMock(return_value={"sub": "invalid-uuid"}),
        )

        credentials = MagicMock()
        credentials.credentials = "token_with_invalid_uuid"
        mock_db = AsyncMock()

        with pytest.raises(UnauthorizedException) as exc:
            await get_current_user(credentials=credentials, db=mock_db)
        assert "Identificador de usuário inválido" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_get_current_user_when_not_in_db_should_raise_unauthorized(
        self, monkeypatch
    ):
        user_id = uuid.uuid4()
        monkeypatch.setattr(
            auth_service,
            "verify_jwt_token",
            AsyncMock(return_value={"sub": str(user_id)}),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        credentials = MagicMock()
        credentials.credentials = "valid_token"

        with pytest.raises(UnauthorizedException) as exc:
            await get_current_user(credentials=credentials, db=mock_db)
        assert "Usuário não encontrado" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_get_current_active_member_when_active_should_return_member(self):
        user = User(id=uuid.uuid4())
        member = OrganizationMember(
            user_id=user.id,
            organization_id=uuid.uuid4(),
            role=OrgRole.TEACHER,
            is_active=True,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = member
        mock_db.execute.return_value = mock_result

        result = await get_current_active_member(current_user=user, db=mock_db)
        assert result == member

    @pytest.mark.asyncio
    async def test_get_current_active_member_when_inactive_should_raise_forbidden(self):
        user = User(id=uuid.uuid4())
        member = OrganizationMember(
            user_id=user.id,
            organization_id=uuid.uuid4(),
            role=OrgRole.STUDENT,
            is_active=False,
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = member
        mock_db.execute.return_value = mock_result

        with pytest.raises(ForbiddenException) as exc:
            await get_current_active_member(current_user=user, db=mock_db)
        assert "desativado" in str(exc.value.message)

    @pytest.mark.asyncio
    async def test_get_current_active_member_when_no_member_should_raise_forbidden(
        self,
    ):
        user = User(id=uuid.uuid4())
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ForbiddenException) as exc:
            await get_current_active_member(current_user=user, db=mock_db)
        assert "não está vinculado" in str(exc.value.message)
