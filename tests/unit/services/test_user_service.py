import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    AuthError,
    NotFoundException,
)
from app.infrastructure.auth import auth_service
from app.models.user import User
from app.services.user_service import user_service


@pytest.mark.asyncio
async def test_user_service_update_profile_and_rollback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    user_id = uuid.uuid4()
    user = User(id=user_id, email="user@svc.com", full_name="Nome Antigo")
    db_session.add(user)
    await db_session.commit()

    # Act 1: Sucesso
    mock_update_auth = AsyncMock()
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update_auth)

    updated = await user_service.update_profile(
        user=user,
        full_name="Nome Novo",
        db=db_session,
    )
    # Assert 1
    assert updated.full_name == "Nome Novo"
    mock_update_auth.assert_called_with(user_id=user_id, full_name="Nome Novo")

    # Act 2 & Assert 2: Falha no auth_service propaga AuthError
    mock_update_auth.side_effect = AuthError("Erro no auth provider", status_code=502)
    with pytest.raises(AuthError) as exc:
        await user_service.update_profile(
            user=user,
            full_name="Outro Nome",
            db=db_session,
        )
    assert exc.value.status_code == 502
    assert exc.value.message == "Erro no auth provider"


@pytest.mark.asyncio
async def test_user_service_update_profile_db_failure_compensatory_rollback(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    user_id = uuid.uuid4()
    user = User(id=user_id, email="user_fail@svc.com", full_name="Nome Original")
    db_session.add(user)
    await db_session.commit()

    mock_update_auth = AsyncMock()
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update_auth)

    # Simula falha no commit do banco
    async def mock_commit_fail() -> None:
        raise RuntimeError("Database write error")

    monkeypatch.setattr(db_session, "commit", mock_commit_fail)

    # Act & Assert
    with pytest.raises(AppException) as exc:
        await user_service.update_profile(
            user=user,
            full_name="Nome Novo Falho",
            db=db_session,
        )

    assert exc.value.status_code == 500
    assert "erro ao atualizar usuário no banco de dados" in exc.value.message.lower()

    # Verifica se update_auth_user foi chamado duas vezes:
    # 1. Atualização para novo nome
    # 2. Rollback compensatório para o nome original
    assert mock_update_auth.await_count == 2
    mock_update_auth.assert_any_await(user_id=user_id, full_name="Nome Novo Falho")
    mock_update_auth.assert_any_await(user_id=user_id, full_name="Nome Original")


@pytest.mark.asyncio
async def test_user_service_update_profile_db_failure_auth_cleanup_error(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    user_id = uuid.uuid4()
    user = User(id=user_id, email="user_cleanup@svc.com", full_name="Nome Original")
    db_session.add(user)
    await db_session.commit()

    # 1º call tem sucesso, 2º call (rollback) falha com AuthError
    mock_update_auth = AsyncMock(
        side_effect=[None, AuthError("Supabase Auth offline", status_code=502)]
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update_auth)

    async def mock_commit_fail() -> None:
        raise RuntimeError("DB connection lost")

    monkeypatch.setattr(db_session, "commit", mock_commit_fail)

    with pytest.raises(AppException) as exc:
        await user_service.update_profile(
            user=user,
            full_name="Nome Novo",
            db=db_session,
        )

    assert exc.value.status_code == 500
    assert mock_update_auth.await_count == 2


@pytest.mark.asyncio
async def test_user_service_get_user_in_org_not_found(db_session: AsyncSession) -> None:
    # Arrange & Act & Assert
    with pytest.raises(NotFoundException) as exc:
        await user_service.get_user_in_org(
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            db=db_session,
        )
    assert exc.value.status_code == 404
    assert exc.value.message == "Usuário não encontrado na organização."
