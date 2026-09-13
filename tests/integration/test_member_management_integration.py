import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import OrgContext


@pytest.mark.asyncio
async def test_owner_registers_teacher_and_student(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida cadastro de professor e aluno pelo Owner com credenciais administrativas reais."""
    uid = uuid.uuid4().hex[:6]
    prof_email = f"prof_{uid}@codeclass-int.com"
    res_prof = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": prof_email,
            "full_name": f"Prof. Alan Turing {uid}",
            "password": "senhaSegura123!",
            "role": "teacher",
        },
    )
    assert res_prof.status_code == 201
    prof_data = res_prof.json()
    registered_org.track_user(prof_data["user_id"])
    assert prof_data["email"] == prof_email
    assert prof_data["role"] == "teacher"
    assert prof_data["is_active"] is True

    # Cadastro do Aluno
    student_email = f"aluno_{uid}@codeclass-int.com"
    res_student = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": student_email,
            "full_name": f"Ada Lovelace {uid}",
            "password": "senhaSegura123!",
            "role": "student",
        },
    )
    assert res_student.status_code == 201
    student_data = res_student.json()
    registered_org.track_user(student_data["user_id"])
    assert student_data["email"] == student_email
    assert student_data["role"] == "student"


@pytest.mark.asyncio
async def test_list_organization_members_with_filters(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida a listagem de membros e a filtragem por papel institucional."""
    uid = uuid.uuid4().hex[:6]
    # Cadastra um professor
    res_prof = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": f"prof_filter_{uid}@codeclass-int.com",
            "full_name": f"Professor Filtro {uid}",
            "password": "senhaSegura123!",
            "role": "teacher",
        },
    )
    assert res_prof.status_code == 201
    registered_org.track_user(res_prof.json()["user_id"])

    # Lista todos os membros
    all_members_res = await async_client.get(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
    )
    assert all_members_res.status_code == 200
    all_members = all_members_res.json()
    assert len(all_members) >= 2  # Owner + Professor

    # Filtra apenas teachers
    teachers_res = await async_client.get(
        f"/api/v1/orgs/{registered_org.org_id}/members?role=teacher",
        headers=registered_org.auth_headers,
    )
    assert teachers_res.status_code == 200
    teachers = teachers_res.json()
    assert len(teachers) >= 1
    assert all(m["role"] == "teacher" for m in teachers)


@pytest.mark.asyncio
async def test_duplicate_member_email_returns_409(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Garante que a tentativa de cadastrar um e-mail já existente é rejeitada."""
    res = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": registered_org.owner_email,
            "full_name": "Tentativa Duplicada",
            "password": "senhaSegura123!",
            "role": "teacher",
        },
    )
    assert res.status_code == 409
