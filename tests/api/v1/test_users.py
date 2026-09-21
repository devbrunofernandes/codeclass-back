import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.auth_service import auth_service
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_update_users_me_full_name_when_valid_should_succeed(
    async_client: AsyncClient, tenant: TenantContext, monkeypatch
):
    # Arrange
    mock_update = AsyncMock(
        return_value={
            "id": tenant.owner.user.id,
            "email": tenant.owner.user.email,
            "full_name": "Novo Nome Completo",
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    # Act
    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"full_name": "Novo Nome Completo"},
    )

    # Assert
    assert res.status_code == 200
    data = res.json()
    assert data["full_name"] == "Novo Nome Completo"
    assert data["email"] == tenant.owner.user.email
    mock_update.assert_awaited_once_with(
        user_id=tenant.owner.user.id,
        full_name="Novo Nome Completo",
    )


@pytest.mark.asyncio
async def test_update_users_me_when_name_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: 1. Nome curto (< 2 caracteres)
    res_short = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"full_name": "A"},
    )
    assert res_short.status_code == 422

    # Act: 2. Corpo vazio (campo obrigatório ausente)
    res_empty = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={},
    )
    assert res_empty.status_code == 422


@pytest.mark.asyncio
async def test_change_password_when_valid_should_return_204(
    async_client: AsyncClient, tenant: TenantContext, monkeypatch
):
    # Arrange
    mock_update = AsyncMock(
        return_value={
            "id": tenant.owner.user.id,
            "email": tenant.owner.user.email,
            "full_name": tenant.owner.user.full_name,
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    # Act
    res = await async_client.put(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"password": "newsecretpassword123"},
    )

    # Assert
    assert res.status_code == 204
    mock_update.assert_awaited_once_with(
        user_id=tenant.owner.user.id,
        password="newsecretpassword123",
    )


@pytest.mark.asyncio
async def test_change_password_when_payload_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Senha curta (< 6 caracteres)
    res = await async_client.put(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"password": "123"},
    )
    assert res.status_code == 422

    # Act: Corpo vazio
    res_empty = await async_client.put(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={},
    )
    assert res_empty.status_code == 422


@pytest.mark.asyncio
async def test_change_password_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
):
    # Act: Requisição sem header de autenticação
    res = await async_client.put(
        "/api/v1/users/me/password",
        json={"password": "newsecretpassword123"},
    )

    # Assert
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_change_password_when_user_is_deactivated_should_return_403(
    async_client: AsyncClient, tenant: TenantContext
):
    # Arrange: Desativa o aluno
    await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/status",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"is_active": False},
    )

    # Act: Aluno inativo tenta trocar senha
    res = await async_client.put(
        "/api/v1/users/me/password",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
        json={"password": "newsecretpassword123"},
    )

    # Assert
    assert res.status_code == 403
    assert "desativado" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_user_by_id_when_same_org_should_succeed(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Owner consulta aluno da mesma instituição
    res = await async_client.get(
        f"/api/v1/users/{tenant.student.user.id}",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
    )

    # Assert
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == str(tenant.student.user.id)
    assert data["email"] == tenant.student.user.email
    assert data["organization_id"] == str(tenant.org.id)


@pytest.mark.asyncio
async def test_get_user_by_id_when_cross_tenant_should_return_404_rnf01(
    async_client: AsyncClient, tenant: TenantContext, create_tenant
):
    # Arrange: Cria outra organização com outro usuário
    other_tenant = await create_tenant("Outra Org")

    # Act: Usuário do Tenant A tenta consultar usuário do Tenant B
    res = await async_client.get(
        f"/api/v1/users/{other_tenant.owner.user.id}",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
    )

    # Assert: Retorna 404 para não vazar a existência do usuário externo
    assert res.status_code == 404
    assert "não encontrado" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_user_by_id_when_user_does_not_exist_should_return_404(
    async_client: AsyncClient, tenant: TenantContext
):
    random_id = uuid.uuid4()

    # Act
    res = await async_client.get(
        f"/api/v1/users/{random_id}",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
    )

    # Assert
    assert res.status_code == 404
    assert "não encontrado" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_users_me_when_database_fails_should_rollback_auth_provider(
    async_client: AsyncClient, tenant: TenantContext, monkeypatch
):
    # Arrange
    user_id = tenant.owner.user.id
    original_name = tenant.owner.user.full_name

    mock_update = AsyncMock(
        return_value={
            "id": user_id,
            "email": tenant.owner.user.email,
            "full_name": "Nome Provisório",
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    # Simula falha no commit do banco
    async def mock_commit_fail(*args, **kwargs):
        raise RuntimeError("Database connection lost")

    monkeypatch.setattr(AsyncSession, "commit", mock_commit_fail)

    # Act
    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
        json={"full_name": "Novo Nome Que Falhará"},
    )

    # Assert
    assert res.status_code == 500
    assert "erro ao atualizar usuário no banco" in res.json()["detail"].lower()

    # Verifica se update_auth_user foi chamado duas vezes:
    # 1. Tentativa original com o novo nome
    # 2. Rollback compensatório com o nome original
    assert mock_update.await_count == 2
    first_call = mock_update.await_args_list[0]
    second_call = mock_update.await_args_list[1]
    assert first_call.kwargs["full_name"] == "Novo Nome Que Falhará"
    assert second_call.kwargs["full_name"] == original_name
