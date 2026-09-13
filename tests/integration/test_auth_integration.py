import pytest
from httpx import AsyncClient

from tests.integration.conftest import OrgContext


@pytest.mark.asyncio
async def test_owner_login_success_and_jwt_claims(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida o login no GoTrue real, verificando estrutura do token e vínculo institucional."""
    res = await async_client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_org.owner_email,
            "password": registered_org.owner_password,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["role"] == "owner"
    assert data["organization_id"] == registered_org.org_id
    assert data["user"]["email"] == registered_org.owner_email


@pytest.mark.asyncio
async def test_get_current_user_profile_me(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida que o token ES256 do Supabase é decodificado e mapeado para o perfil completo."""
    res = await async_client.get(
        "/api/v1/auth/me",
        headers=registered_org.auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == registered_org.owner_id
    assert data["email"] == registered_org.owner_email
    assert data["full_name"] == registered_org.owner_name
    assert data["role"] == "owner"
    assert data["organization_id"] == registered_org.org_id
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_refresh_token_flow(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida a rotação de tokens através do refresh token real."""
    res = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": registered_org.refresh_token},
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data

    # Testa que o novo access token funciona imediatamente
    me_res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me_res.status_code == 200


@pytest.mark.asyncio
async def test_login_invalid_password_returns_401(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida que credenciais incorretas são rejeitadas pelo Supabase Auth."""
    res = await async_client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_org.owner_email,
            "password": "senhaIncorretaErrada!",
        },
    )
    assert res.status_code == 401
    assert "Credenciais inválidas" in res.json()["detail"]
