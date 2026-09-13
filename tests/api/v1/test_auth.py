import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.user import User
from app.services.auth_service import AuthError, auth_service


@pytest.fixture
async def sample_user_and_org(async_client: AsyncClient, create_access_token, monkeypatch):
    owner_id = uuid.uuid4()
    slug = f"org-auth-{owner_id.hex[:6]}"
    email = f"auth_owner_{owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": email, "full_name": "Auth Owner"}),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Auth Test",
            "slug": slug,
            "owner": {"email": email, "full_name": "Auth Owner", "password": "securepassword123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]
    token = create_access_token(owner_id, email=email, full_name="Auth Owner")
    return {
        "org_id": org_id,
        "owner_id": owner_id,
        "email": email,
        "token": token,
        "slug": slug,
    }


@pytest.mark.asyncio
async def test_login_success(async_client: AsyncClient, sample_user_and_org, monkeypatch):
    user_data = sample_user_and_org
    owner_id = user_data["owner_id"]
    email = user_data["email"]

    mock_signin = AsyncMock(return_value={
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "user_id": owner_id,
        "email": email,
        "full_name": "Auth Owner",
    })
    monkeypatch.setattr(auth_service, "sign_in_with_password", mock_signin)

    res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "securepassword123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"] == "mock-access-token"
    assert data["refresh_token"] == "mock-refresh-token"
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email
    assert data["role"] == OrgRole.OWNER.value
    assert data["organization_id"] == user_data["org_id"]


@pytest.mark.asyncio
async def test_login_invalid_credentials(async_client: AsyncClient, monkeypatch):
    mock_signin = AsyncMock(side_effect=AuthError("Credenciais inválidas.", status_code=401))
    monkeypatch.setattr(auth_service, "sign_in_with_password", mock_signin)

    res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": "wrong@example.com", "password": "wrongpassword"},
    )
    assert res.status_code == 401
    assert "Credenciais inválidas" in res.json()["detail"]


@pytest.mark.asyncio
async def test_get_me_success(async_client: AsyncClient, sample_user_and_org):
    user_data = sample_user_and_org
    token = user_data["token"]

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(user_data["owner_id"])
    assert data["email"] == user_data["email"]
    assert data["full_name"] == "Auth Owner"
    assert data["organization_id"] == user_data["org_id"]
    assert data["organization_slug"] == user_data["slug"]
    assert data["role"] == OrgRole.OWNER.value
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_get_me_unauthorized(async_client: AsyncClient):
    res = await async_client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(async_client: AsyncClient, monkeypatch):
    mock_refresh = AsyncMock(return_value={
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "user_id": str(uuid.uuid4()),
        "email": "user@example.com",
    })
    monkeypatch.setattr(auth_service, "refresh_session", mock_refresh)

    res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "valid-refresh-token"},
    )
    assert res.status_code == 200
    assert res.json()["access_token"] == "new-access-token"


@pytest.mark.asyncio
async def test_login_deactivated_user(async_client: AsyncClient, sample_user_and_org, monkeypatch):
    user_data = sample_user_and_org
    owner_token = user_data["token"]
    org_id = user_data["org_id"]

    # 1. Cadastra um aluno
    student_id = uuid.uuid4()
    student_email = f"deact_{student_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": student_id, "email": student_email, "full_name": "Aluno Inativo"}),
    )
    await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": student_email,
            "full_name": "Aluno Inativo",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )

    # 2. Desativa o aluno
    await async_client.patch(
        f"/api/v1/orgs/{org_id}/members/{student_id}/status",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"is_active": False},
    )

    # 3. Aluno tenta efetuar login (bloqueio 403)
    mock_signin = AsyncMock(return_value={
        "access_token": "token-deact",
        "refresh_token": "refresh-deact",
        "user_id": student_id,
        "email": student_email,
        "full_name": "Aluno Inativo",
    })
    monkeypatch.setattr(auth_service, "sign_in_with_password", mock_signin)

    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": student_email, "password": "password123"},
    )
    assert login_res.status_code == 403
    assert "desativado" in login_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_user_without_organization_returns_403(
    async_client: AsyncClient, monkeypatch, db_session: AsyncSession
):
    orphan_id = uuid.uuid4()
    orphan_email = f"orphan_{orphan_id.hex[:6]}@example.com"

    mock_signin = AsyncMock(return_value={
        "access_token": "orphan-token",
        "refresh_token": "orphan-refresh",
        "user_id": orphan_id,
        "email": orphan_email,
        "full_name": "Usuário Sem Org",
    })
    monkeypatch.setattr(auth_service, "sign_in_with_password", mock_signin)

    res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": orphan_email, "password": "password123"},
    )
    assert res.status_code == 403
    assert "vínculo" in res.json()["detail"].lower()

    # Confirma que o usuário NÃO foi persistido como órfão no banco de dados
    assert await db_session.get(User, orphan_id) is None

