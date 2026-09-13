import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import OrgContext


@pytest.mark.asyncio
async def test_update_member_role(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida a atualização do papel de um membro da organização."""
    uid = uuid.uuid4().hex[:6]
    # Cadastra Aluno
    res = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": f"aluno_role_{uid}@codeclass-int.com",
            "full_name": f"Aluno Role {uid}",
            "password": "senhaSegura123!",
            "role": "student",
        },
    )
    assert res.status_code == 201
    student_id = res.json()["user_id"]
    registered_org.track_user(student_id)

    # Promove para Teacher
    update_res = await async_client.put(
        f"/api/v1/orgs/{registered_org.org_id}/members/{student_id}/role",
        headers=registered_org.auth_headers,
        json={"role": "teacher"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["role"] == "teacher"


@pytest.mark.asyncio
async def test_deactivate_member_blocks_subsequent_login(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida que um membro desativado é bloqueado no login mesmo com credenciais válidas no Supabase Auth."""
    uid = uuid.uuid4().hex[:6]
    email = f"aluno_deact_{uid}@codeclass-int.com"
    password = "senhaSegura123!"

    # Cadastra Aluno
    res = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": email,
            "full_name": f"Aluno Deact {uid}",
            "password": password,
            "role": "student",
        },
    )
    assert res.status_code == 201
    student_id = res.json()["user_id"]
    registered_org.track_user(student_id)

    # Desativa o membro
    deact_res = await async_client.patch(
        f"/api/v1/orgs/{registered_org.org_id}/members/{student_id}/status",
        headers=registered_org.auth_headers,
        json={"is_active": False},
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Tenta efetuar login com o usuário desativado
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 403
    assert "desativado" in login_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_deactivate_self_or_owner(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Garante que o Owner não pode desativar a própria conta da organização."""
    res = await async_client.patch(
        f"/api/v1/orgs/{registered_org.org_id}/members/{registered_org.owner_id}/status",
        headers=registered_org.auth_headers,
        json={"is_active": False},
    )
    assert res.status_code == 400
