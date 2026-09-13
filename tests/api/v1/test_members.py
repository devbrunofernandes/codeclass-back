import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.models.enums import OrgRole
from app.services.auth_service import auth_service


@pytest.fixture
async def setup_org_and_owner(async_client: AsyncClient, create_access_token, monkeypatch):
    owner_id = uuid.uuid4()
    slug = f"org-members-{owner_id.hex[:6]}"
    email = f"owner_{owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": owner_id, "email": email, "full_name": "Org Owner"}),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Membros Teste",
            "slug": slug,
            "owner": {"email": email, "full_name": "Org Owner", "password": "password123"},
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]
    token = create_access_token(owner_id, email=email, full_name="Org Owner")
    return {"org_id": org_id, "owner_id": owner_id, "owner_token": token, "email": email}


@pytest.mark.asyncio
async def test_member_registration_and_rbac(
    async_client: AsyncClient, setup_org_and_owner, create_access_token, monkeypatch
):
    org_data = setup_org_and_owner
    org_id = org_data["org_id"]
    owner_token = org_data["owner_token"]

    # 1. Owner cadastra um Admin
    admin_id = uuid.uuid4()
    admin_email = f"admin_{admin_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": admin_id, "email": admin_email, "full_name": "Admin User"}),
    )
    res_admin = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": admin_email,
            "full_name": "Admin User",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    assert res_admin.status_code == 201
    assert res_admin.json()["role"] == OrgRole.ADMIN.value
    admin_token = create_access_token(admin_id, email=admin_email, full_name="Admin User")

    # 2. Admin tenta cadastrar outro Admin (Bloqueio 403 - Apenas Owner pode criar Admins)
    sub_admin_id = uuid.uuid4()
    res_fail = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": f"sub_{sub_admin_id.hex[:6]}@example.com",
            "full_name": "Sub Admin",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    assert res_fail.status_code == 403

    # 3. Admin cadastra um Professor (Sucesso 201)
    teacher_id = uuid.uuid4()
    teacher_email = f"teacher_{teacher_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": teacher_id, "email": teacher_email, "full_name": "Teacher User"}),
    )
    res_teacher = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": teacher_email,
            "full_name": "Teacher User",
            "password": "password123",
            "role": OrgRole.TEACHER.value,
        },
    )
    assert res_teacher.status_code == 201
    teacher_token = create_access_token(teacher_id, email=teacher_email, full_name="Teacher User")

    # 4. Professor tenta cadastrar Aluno (Bloqueio 403 - Apenas Owner ou Admin podem cadastrar membros)
    student_id = uuid.uuid4()
    res_teacher_fail = await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {teacher_token}"},
        json={
            "email": f"stud_{student_id.hex[:6]}@example.com",
            "full_name": "Student User",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )
    assert res_teacher_fail.status_code == 403


@pytest.mark.asyncio
async def test_list_members_and_filters(
    async_client: AsyncClient, setup_org_and_owner, monkeypatch
):
    org_data = setup_org_and_owner
    org_id = org_data["org_id"]
    owner_token = org_data["owner_token"]

    # Listar membros
    res = await async_client.get(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res.status_code == 200
    members = res.json()
    assert len(members) >= 1
    assert any(m["role"] == OrgRole.OWNER.value for m in members)


@pytest.mark.asyncio
async def test_update_member_role_and_status(
    async_client: AsyncClient, setup_org_and_owner, create_access_token, monkeypatch
):
    org_data = setup_org_and_owner
    org_id = org_data["org_id"]
    owner_token = org_data["owner_token"]

    # Cria aluno
    student_id = uuid.uuid4()
    student_email = f"student_{student_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": student_id, "email": student_email, "full_name": "Student User"}),
    )
    await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": student_email,
            "full_name": "Student User",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )

    # Owner promove aluno para professor
    put_role = await async_client.put(
        f"/api/v1/orgs/{org_id}/members/{student_id}/role",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": OrgRole.TEACHER.value},
    )
    assert put_role.status_code == 200
    assert put_role.json()["role"] == OrgRole.TEACHER.value

    # Owner desativa o membro
    patch_status = await async_client.patch(
        f"/api/v1/orgs/{org_id}/members/{student_id}/status",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"is_active": False},
    )
    assert patch_status.status_code == 200
    assert patch_status.json()["is_active"] is False

    # Desativado tenta acessar recursos da org -> 403
    inactive_token = create_access_token(student_id, email=student_email, full_name="Student User")
    access_res = await async_client.get(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {inactive_token}"},
    )
    assert access_res.status_code == 403


@pytest.mark.asyncio
async def test_transfer_ownership(
    async_client: AsyncClient, setup_org_and_owner, create_access_token, monkeypatch
):
    org_data = setup_org_and_owner
    org_id = org_data["org_id"]
    old_owner_id = org_data["owner_id"]
    old_owner_token = org_data["owner_token"]

    # Cria novo membro (professor)
    new_owner_id = uuid.uuid4()
    new_owner_email = f"new_owner_{new_owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": new_owner_id, "email": new_owner_email, "full_name": "Novo Dono"}),
    )
    await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {old_owner_token}"},
        json={
            "email": new_owner_email,
            "full_name": "Novo Dono",
            "password": "password123",
            "role": OrgRole.TEACHER.value,
        },
    )

    # Transfere titularidade
    transfer_res = await async_client.put(
        f"/api/v1/orgs/{org_id}/owner",
        headers={"Authorization": f"Bearer {old_owner_token}"},
        json={"new_owner_id": str(new_owner_id)},
    )
    assert transfer_res.status_code == 200
    assert transfer_res.json()["owner_id"] == str(new_owner_id)

    # Verifica lista de membros: antigo dono deve ser admin, novo dono deve ser owner
    new_owner_token = create_access_token(new_owner_id, email=new_owner_email, full_name="Novo Dono")
    members_res = await async_client.get(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {new_owner_token}"},
    )
    members_by_id = {m["user_id"]: m for m in members_res.json()}
    assert members_by_id[str(old_owner_id)]["role"] == OrgRole.ADMIN.value
    assert members_by_id[str(new_owner_id)]["role"] == OrgRole.OWNER.value


@pytest.mark.asyncio
async def test_prevent_self_and_owner_deactivation(
    async_client: AsyncClient, setup_org_and_owner, create_access_token, monkeypatch
):
    org_data = setup_org_and_owner
    org_id = org_data["org_id"]
    owner_id = org_data["owner_id"]
    owner_token = org_data["owner_token"]

    # 1. Tentativa de auto-desativação do Owner (bloqueio 400)
    res_self = await async_client.patch(
        f"/api/v1/orgs/{org_id}/members/{owner_id}/status",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"is_active": False},
    )
    assert res_self.status_code == 400
    assert "próprio status" in res_self.json()["detail"].lower()

    # 2. Cadastra um Admin
    admin_id = uuid.uuid4()
    admin_email = f"adm_{admin_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(return_value={"id": admin_id, "email": admin_email, "full_name": "Admin"}),
    )
    await async_client.post(
        f"/api/v1/orgs/{org_id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={
            "email": admin_email,
            "full_name": "Admin",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    admin_token = create_access_token(admin_id, email=admin_email, full_name="Admin")

    # 3. Admin tenta desativar o Owner (bloqueio 400)
    res_owner_deact = await async_client.patch(
        f"/api/v1/orgs/{org_id}/members/{owner_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": False},
    )
    assert res_owner_deact.status_code == 400
    assert "proprietário" in res_owner_deact.json()["detail"].lower()

