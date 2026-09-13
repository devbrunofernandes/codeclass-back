import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.services.auth_service import auth_service


@pytest.fixture
async def setup_user_and_org(async_client: AsyncClient, create_access_token, monkeypatch):
    owner_id = uuid.uuid4()
    slug = f"org-users-{owner_id.hex[:6]}"
    email = f"user_owner_{owner_id.hex[:6]}@example.com"
    full_name = "User Owner"

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": email, "full_name": full_name}),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Users Test",
            "slug": slug,
            "owner": {"email": email, "full_name": full_name, "password": "password123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]
    token = create_access_token(owner_id, email=email, full_name=full_name)
    return {
        "org_id": org_id,
        "user_id": owner_id,
        "email": email,
        "full_name": full_name,
        "token": token,
        "slug": slug,
    }


@pytest.mark.asyncio
async def test_update_users_me_full_name(async_client: AsyncClient, setup_user_and_org, monkeypatch):
    user_data = setup_user_and_org
    token = user_data["token"]

    mock_update = AsyncMock(
        return_value={
            "id": user_data["user_id"],
            "email": user_data["email"],
            "full_name": "Novo Nome Completo",
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Novo Nome Completo"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["full_name"] == "Novo Nome Completo"
    assert data["email"] == user_data["email"]
    mock_update.assert_awaited_once_with(
        user_id=user_data["user_id"],
        full_name="Novo Nome Completo",
        password=None,
    )


@pytest.mark.asyncio
async def test_update_users_me_password(async_client: AsyncClient, setup_user_and_org, monkeypatch):
    user_data = setup_user_and_org
    token = user_data["token"]

    mock_update = AsyncMock(
        return_value={
            "id": user_data["user_id"],
            "email": user_data["email"],
            "full_name": user_data["full_name"],
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "newsecretpassword123"},
    )
    assert res.status_code == 200
    mock_update.assert_awaited_once_with(
        user_id=user_data["user_id"],
        full_name=None,
        password="newsecretpassword123",
    )


@pytest.mark.asyncio
async def test_update_users_me_both_name_and_password(
    async_client: AsyncClient, setup_user_and_org, monkeypatch
):
    user_data = setup_user_and_org
    token = user_data["token"]

    mock_update = AsyncMock(
        return_value={
            "id": user_data["user_id"],
            "email": user_data["email"],
            "full_name": "Nome Atualizado",
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Nome Atualizado", "password": "novasenhaforte456"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["full_name"] == "Nome Atualizado"
    mock_update.assert_awaited_once_with(
        user_id=user_data["user_id"],
        full_name="Nome Atualizado",
        password="novasenhaforte456",
    )


@pytest.mark.asyncio
async def test_update_users_me_empty_body(async_client: AsyncClient, setup_user_and_org):
    user_data = setup_user_and_org
    token = user_data["token"]

    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert res.status_code == 400
    assert "pelo menos um campo" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_users_me_validation_errors(async_client: AsyncClient, setup_user_and_org):
    user_data = setup_user_and_org
    token = user_data["token"]

    # Senha curta (< 6 caracteres)
    res_pass = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": "123"},
    )
    assert res_pass.status_code == 422

    # Nome curto (< 2 caracteres)
    res_name = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "A"},
    )
    assert res_name.status_code == 422


@pytest.mark.asyncio
async def test_get_user_by_id_same_org(
    async_client: AsyncClient, setup_user_and_org, monkeypatch
):
    user_data = setup_user_and_org
    owner_token = user_data["token"]
    org_id = user_data["org_id"]

    student_id = uuid.uuid4()
    student_email = f"student_{student_id.hex[:6]}@example.com"
    student_name = "Estudante da Mesma Org"

    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": student_id, "email": student_email, "full_name": student_name}),
    )

    # Cadastra o estudante na organização
    res_member = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": student_email,
            "full_name": student_name,
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )
    assert res_member.status_code == 201

    # Consulta o estudante via GET /users/{student_id}
    res = await async_client.get(
        f"/api/v1/users/{student_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == str(student_id)
    assert data["email"] == student_email
    assert data["full_name"] == student_name
    assert data["organization_id"] == str(org_id)
    assert data["role"] == OrgRole.STUDENT.value
    assert data["is_active"] is True
    assert "joined_at" in data


@pytest.mark.asyncio
async def test_get_user_by_id_cross_tenant_isolation_returns_404(
    async_client: AsyncClient, setup_user_and_org, create_access_token, monkeypatch
):
    """Garante que consultar um usuário de outra organização retorna 404 (RNF01 - Isolamento Multi-tenant)."""
    user_data = setup_user_and_org
    owner_token = user_data["token"]

    # Cria uma segunda organização com outro usuário
    org2_owner_id = uuid.uuid4()
    org2_email = f"other_org_{org2_owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": org2_owner_id, "email": org2_email, "full_name": "Other Owner"}),
    )
    res_org2 = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Isolada 2",
            "slug": f"org-isolada-{org2_owner_id.hex[:6]}",
            "owner": {"email": org2_email, "full_name": "Other Owner", "password": "password123"},
        },
    )
    assert res_org2.status_code == 201

    # O usuário da Org 1 tenta consultar o usuário da Org 2
    res = await async_client.get(
        f"/api/v1/users/{org2_owner_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    # Deve retornar 404 para não vazar a existência do usuário em outro tenant
    assert res.status_code == 404
    assert "não encontrado" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(async_client: AsyncClient, setup_user_and_org):
    user_data = setup_user_and_org
    token = user_data["token"]
    random_id = uuid.uuid4()

    res = await async_client.get(
        f"/api/v1/users/{random_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404
    assert "não encontrado" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_update_users_me_database_failure_triggers_compensating_rollback(
    async_client: AsyncClient, setup_user_and_org, monkeypatch
):
    user_data = setup_user_and_org
    token = user_data["token"]
    user_id = user_data["user_id"]
    original_name = user_data["full_name"]

    mock_update = AsyncMock(
        return_value={
            "id": user_id,
            "email": user_data["email"],
            "full_name": "Nome Provisório",
        }
    )
    monkeypatch.setattr(auth_service, "update_auth_user", mock_update)

    # Simula falha catastrófica no commit do banco
    async def mock_commit_fail(*args, **kwargs):
        raise RuntimeError("Database connection lost")

    monkeypatch.setattr(AsyncSession, "commit", mock_commit_fail)

    res = await async_client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Novo Nome Que Falhará"},
    )
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
