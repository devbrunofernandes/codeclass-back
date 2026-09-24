import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import auth_service
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_register_organization_when_valid_should_create_organization_and_owner(
    async_client: AsyncClient, monkeypatch
):
    # Arrange
    owner_id = uuid.uuid4()
    mock_create = AsyncMock(
        return_value={
            "id": owner_id,
            "email": f"owner_{owner_id.hex[:6]}@example.com",
            "full_name": "Org Owner",
        }
    )
    monkeypatch.setattr(auth_service, "create_auth_user", mock_create)

    slug = f"univ-{owner_id.hex[:6]}"
    email = f"owner_{owner_id.hex[:6]}@example.com"
    payload = {
        "name": "Universidade Exemplo",
        "slug": slug,
        "owner": {
            "email": email,
            "full_name": "Org Owner",
            "password": "strongpassword123",
        },
    }

    # Act
    response = await async_client.post("/api/v1/orgs", json=payload)

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Universidade Exemplo"
    assert data["slug"] == slug
    assert data["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_register_organization_when_payload_is_invalid_should_return_422(
    async_client: AsyncClient,
):
    # Arrange: payload sem campos obrigatórios
    payload = {"name": "Org Sem Slug"}

    # Act
    response = await async_client.post("/api/v1/orgs", json=payload)

    # Assert
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_organization_when_slug_is_duplicated_should_return_409(
    async_client: AsyncClient, monkeypatch
):
    # Arrange
    first_owner_id = uuid.uuid4()
    second_owner_id = uuid.uuid4()
    slug = f"dup-slug-{first_owner_id.hex[:6]}"

    mock_create = AsyncMock(
        side_effect=[
            {
                "id": first_owner_id,
                "email": f"user1_{first_owner_id.hex[:6]}@example.com",
                "full_name": "User 1",
            },
            {
                "id": second_owner_id,
                "email": f"user2_{second_owner_id.hex[:6]}@example.com",
                "full_name": "User 2",
            },
        ]
    )
    monkeypatch.setattr(auth_service, "create_auth_user", mock_create)

    payload1 = {
        "name": "Org 1",
        "slug": slug,
        "owner": {
            "email": f"user1_{first_owner_id.hex[:6]}@example.com",
            "full_name": "User 1",
            "password": "password123",
        },
    }
    res1 = await async_client.post("/api/v1/orgs", json=payload1)
    assert res1.status_code == 201

    payload2 = {
        "name": "Org 2",
        "slug": slug,
        "owner": {
            "email": f"user2_{second_owner_id.hex[:6]}@example.com",
            "full_name": "User 2",
            "password": "password123",
        },
    }

    # Act
    res2 = await async_client.post("/api/v1/orgs", json=payload2)

    # Assert
    assert res2.status_code == 409
    assert "slug" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_organization_and_tenant_isolation_should_enforce_rnf01(
    async_client: AsyncClient, tenant: TenantContext, create_tenant
):
    # Arrange: Cria segundo tenant
    other_tenant = await create_tenant("Outra Org")

    # Act & Assert: Owner 1 acessa Org 1 com sucesso -> 200
    get_res1 = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
    )
    assert get_res1.status_code == 200
    assert get_res1.json()["id"] == str(tenant.org.id)

    # Act & Assert: Owner 2 tenta acessar Org 1 -> bloqueio 403 (RNF01)
    get_res2 = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=other_tenant.owner.auth_headers,
    )
    assert get_res2.status_code == 403

    # Act & Assert: Owner 1 tenta acessar Org 2 -> bloqueio 403 (RNF01)
    get_res3 = await async_client.get(
        f"/api/v1/orgs/{other_tenant.org.id}",
        headers=tenant.owner.auth_headers,
    )
    assert get_res3.status_code == 403


@pytest.mark.asyncio
async def test_update_and_delete_organization_lifecycle(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    # Act: PATCH (Atualizar nome)
    patch_res = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
        json={"name": "Nome Atualizado"},
    )
    # Assert
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Nome Atualizado"

    # Act: DELETE
    del_res = await async_client.delete(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
    )
    # Assert
    assert del_res.status_code == 204

    # Consulta pós-exclusão com o token do usuário deletado retorna 401 (usuário removido)
    get_res = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
    )
    assert get_res.status_code == 401

    # Validação direta no banco: Organization e User foram removidos
    async with async_session_maker() as verify_session:
        assert await verify_session.get(Organization, tenant.org.id) is None
        assert await verify_session.get(User, tenant.owner.user.id) is None


@pytest.mark.asyncio
async def test_delete_organization_deletes_all_members_and_users(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    # Arrange: Garante que existem múltiplos usuários antes da exclusão
    assert await db_session.get(User, tenant.owner.user.id) is not None
    assert await db_session.get(User, tenant.teacher.user.id) is not None
    assert await db_session.get(User, tenant.student.user.id) is not None

    # Act: Deleta a organização
    del_res = await async_client.delete(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
    )
    # Assert
    assert del_res.status_code == 204

    # Valida que a organização e TODOS os usuários vinculados foram removidos do banco
    async with async_session_maker() as verify_session:
        assert await verify_session.get(Organization, tenant.org.id) is None
        assert await verify_session.get(User, tenant.owner.user.id) is None
        assert await verify_session.get(User, tenant.teacher.user.id) is None
        assert await verify_session.get(User, tenant.student.user.id) is None


@pytest.mark.asyncio
async def test_list_organization_classrooms_admin_and_owner(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Consulta salas da org
    cls_res = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        headers=tenant.owner.auth_headers,
    )

    # Assert
    assert cls_res.status_code == 200
    assert isinstance(cls_res.json(), list)


@pytest.mark.asyncio
async def test_organization_and_transfer_ownership_edge_cases(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_tenant,
):
    # 1. Conflito de slug ao tentar usar o slug de outra organização existente -> 409
    other_tenant = await create_tenant("Outra Org")
    res_conflict = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}",
        headers=tenant.owner.auth_headers,
        json={"slug": other_tenant.org.slug},
    )
    assert res_conflict.status_code == 409

    # 2. Transferir posse para si mesmo -> 400
    res_transfer_self = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/owner",
        headers=tenant.owner.auth_headers,
        json={"new_owner_id": str(tenant.owner.user.id)},
    )
    assert res_transfer_self.status_code == 400

    # 3. Transferir posse para usuário inexistente / não membro -> 404
    non_member_id = uuid.uuid4()
    res_transfer_nf = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/owner",
        headers=tenant.owner.auth_headers,
        json={"new_owner_id": str(non_member_id)},
    )
    assert res_transfer_nf.status_code == 404

    # 4. Desativa membro e tenta transferir posse para membro inativo -> 400
    await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/status",
        headers=tenant.owner.auth_headers,
        json={"is_active": False},
    )

    res_transfer_inactive = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/owner",
        headers=tenant.owner.auth_headers,
        json={"new_owner_id": str(tenant.student.user.id)},
    )
    assert res_transfer_inactive.status_code == 400
    assert "desativado" in res_transfer_inactive.json()["detail"].lower()
