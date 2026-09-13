import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import auth_service


@pytest.mark.asyncio
async def test_register_organization_success(async_client: AsyncClient, monkeypatch):
    owner_id = uuid.uuid4()
    mock_create = AsyncMock(return_value={
        "id": owner_id,
        "email": f"owner_{owner_id.hex[:6]}@example.com",
        "full_name": "Org Owner",
    })
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

    response = await async_client.post("/api/v1/orgs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Universidade Exemplo"
    assert data["slug"] == slug
    assert data["owner_id"] == str(owner_id)


@pytest.mark.asyncio
async def test_register_organization_duplicate_slug(async_client: AsyncClient, monkeypatch):
    first_owner_id = uuid.uuid4()
    second_owner_id = uuid.uuid4()
    slug = f"dup-slug-{first_owner_id.hex[:6]}"

    mock_create = AsyncMock(side_effect=[
        {"id": first_owner_id, "email": f"user1_{first_owner_id.hex[:6]}@example.com", "full_name": "User 1"},
        {"id": second_owner_id, "email": f"user2_{second_owner_id.hex[:6]}@example.com", "full_name": "User 2"},
    ])
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
    res2 = await async_client.post("/api/v1/orgs", json=payload2)
    assert res2.status_code == 409
    assert "slug" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_organization_and_tenant_isolation(
    async_client: AsyncClient, create_access_token, monkeypatch
):
    # Cadastra Org 1
    org1_owner_id = uuid.uuid4()
    slug1 = f"org1-{org1_owner_id.hex[:6]}"
    email1 = f"owner_{org1_owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": org1_owner_id, "email": email1, "full_name": "Owner 1"}),
    )
    res1 = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org 1",
            "slug": slug1,
            "owner": {"email": email1, "full_name": "Owner 1", "password": "password123"},
        },
    )
    assert res1.status_code == 201
    org1_id = res1.json()["id"]

    # Cadastra Org 2
    org2_owner_id = uuid.uuid4()
    slug2 = f"org2-{org2_owner_id.hex[:6]}"
    email2 = f"owner_{org2_owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": org2_owner_id, "email": email2, "full_name": "Owner 2"}),
    )
    res2 = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org 2",
            "slug": slug2,
            "owner": {"email": email2, "full_name": "Owner 2", "password": "password123"},
        },
    )
    assert res2.status_code == 201
    org2_id = res2.json()["id"]

    # Token do Owner 1
    token1 = create_access_token(org1_owner_id, email=email1, full_name="Owner 1")
    # Token do Owner 2
    token2 = create_access_token(org2_owner_id, email=email2, full_name="Owner 2")

    # Owner 1 acessa Org 1 (sucesso 200)
    get_res1 = await async_client.get(
        f"/api/v1/orgs/{org1_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert get_res1.status_code == 200
    assert get_res1.json()["slug"] == slug1

    # Owner 2 tenta acessar Org 1 (bloqueio 403 RNF01 isolamento multi-tenant)
    get_res2 = await async_client.get(
        f"/api/v1/orgs/{org1_id}",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert get_res2.status_code == 403

    # Owner 1 tenta acessar Org 2 (bloqueio 403)
    get_res3 = await async_client.get(
        f"/api/v1/orgs/{org2_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert get_res3.status_code == 403


@pytest.mark.asyncio
async def test_update_and_delete_organization_owner(
    async_client: AsyncClient, create_access_token, monkeypatch, db_session: AsyncSession
):
    owner_id = uuid.uuid4()
    slug = f"org-up-{owner_id.hex[:6]}"
    email = f"owner_{owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": email, "full_name": "Owner"}),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Nome Original",
            "slug": slug,
            "owner": {"email": email, "full_name": "Owner", "password": "password123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]

    token = create_access_token(owner_id, email=email, full_name="Owner")

    # PATCH (Atualizar nome)
    patch_res = await async_client.patch(
        f"/api/v1/orgs/{org_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Nome Atualizado"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Nome Atualizado"

    # DELETE
    del_res = await async_client.delete(
        f"/api/v1/orgs/{org_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 204

    # Consulta pós-exclusão com o token do usuário deletado retorna 401 (usuário não existe mais)
    get_res = await async_client.get(
        f"/api/v1/orgs/{org_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 401

    # Validação direta no banco: Organization e User foram removidos
    assert await db_session.get(Organization, uuid.UUID(org_id)) is None
    assert await db_session.get(User, owner_id) is None


@pytest.mark.asyncio
async def test_delete_organization_deletes_all_members_and_users(
    async_client: AsyncClient, create_access_token, monkeypatch, db_session: AsyncSession
):
    owner_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    org_slug = f"org-del-{owner_id.hex[:6]}"
    owner_email = f"owner_{owner_id.hex[:6]}@example.com"
    teacher_email = f"teacher_{teacher_id.hex[:6]}@example.com"

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": owner_email, "full_name": "Owner"}),
    )

    # 1. Cria organização
    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Multi Membros",
            "slug": org_slug,
            "owner": {"email": owner_email, "full_name": "Owner", "password": "password123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]
    owner_token = create_access_token(owner_id, email=owner_email, full_name="Owner")

    # 2. Adiciona um professor
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": teacher_id, "email": teacher_email, "full_name": "Teacher"}),
    )
    member_res = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": teacher_email,
            "full_name": "Teacher",
            "password": "password123",
            "role": OrgRole.TEACHER.value,
        },
    )
    assert member_res.status_code == 201

    # Confirma que ambos existem no banco
    assert await db_session.get(User, owner_id) is not None
    assert await db_session.get(User, teacher_id) is not None

    # 3. Deleta a organização
    del_res = await async_client.delete(
        f"/api/v1/orgs/{org_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_res.status_code == 204

    # 4. Verifica no banco que a organização e TODOS os usuários foram removidos
    assert await db_session.get(Organization, uuid.UUID(org_id)) is None
    assert await db_session.get(User, owner_id) is None
    assert await db_session.get(User, teacher_id) is None


@pytest.mark.asyncio
async def test_list_organization_classrooms_admin_and_owner(
    async_client: AsyncClient, create_access_token, monkeypatch
):
    owner_id = uuid.uuid4()
    slug = f"org-cls-{owner_id.hex[:6]}"
    email = f"owner_{owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": email, "full_name": "Owner"}),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Salas",
            "slug": slug,
            "owner": {"email": email, "full_name": "Owner", "password": "password123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]

    token = create_access_token(owner_id, email=email, full_name="Owner")

    # Consulta salas da org (deve retornar 200 e lista vazia inicialmente)
    cls_res = await async_client.get(
        f"/api/v1/orgs/{org_id}/classrooms",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cls_res.status_code == 200
    assert isinstance(cls_res.json(), list)

