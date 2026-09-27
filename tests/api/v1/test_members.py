import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.infrastructure.auth import auth_service
from app.models.enums import OrgRole
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_add_member_rbac_permissions(
    async_client: AsyncClient,
    tenant: TenantContext,
    monkeypatch,
):
    # Arrange: Mock de criação de usuário no auth
    new_admin_id = uuid.uuid4()
    admin_email = f"new_admin_{new_admin_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={
                "id": new_admin_id,
                "email": admin_email,
                "full_name": "New Admin",
            }
        ),
    )

    # Act & Assert: 1. Owner cadastra um Admin -> 201
    res_admin = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": admin_email,
            "full_name": "New Admin",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    assert res_admin.status_code == 201
    assert res_admin.json()["role"] == OrgRole.ADMIN.value

    # Act & Assert: 2. Admin tenta cadastrar outro Admin -> 403 (Apenas Owner pode criar Admins)
    sub_admin_id = uuid.uuid4()
    res_fail = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.admin.auth_headers,
        json={
            "email": f"sub_{sub_admin_id.hex[:6]}@example.com",
            "full_name": "Sub Admin",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    assert res_fail.status_code == 403

    # Act & Assert: 3. Admin cadastra um Professor -> 201
    new_t_id = uuid.uuid4()
    new_t_email = f"teacher_novo_{new_t_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={
                "id": new_t_id,
                "email": new_t_email,
                "full_name": "Novo Professor",
            }
        ),
    )
    res_t = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.admin.auth_headers,
        json={
            "email": new_t_email,
            "full_name": "Novo Professor",
            "password": "password123",
            "role": OrgRole.TEACHER.value,
        },
    )
    assert res_t.status_code == 201

    # Act & Assert: 4. Professor tenta cadastrar Aluno -> 403 (apenas Admin ou Owner podem)
    res_t_fail = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.teacher.auth_headers,
        json={
            "email": "student_tentativa@example.com",
            "full_name": "Tentativa Aluno",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )
    assert res_t_fail.status_code == 403


@pytest.mark.asyncio
async def test_add_member_when_email_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Envia e-mail em formato inválido
    res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": "invalid-email-format",
            "full_name": "Nome Valido",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )

    # Assert
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_members_with_filters_search_and_pagination(
    async_client: AsyncClient, tenant: TenantContext, monkeypatch
):
    # Arrange: Adiciona professor ativo e aluno desativado
    t_id = uuid.uuid4()
    t_email = f"prof_filtro_{t_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={
                "id": t_id,
                "email": t_email,
                "full_name": "Professor Filtro",
            }
        ),
    )
    await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": t_email,
            "full_name": "Professor Filtro",
            "password": "password123",
            "role": OrgRole.TEACHER.value,
        },
    )

    s_id = uuid.uuid4()
    s_email = f"aluno_filtro_{s_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={
                "id": s_id,
                "email": s_email,
                "full_name": "Aluno Desativado",
            }
        ),
    )
    await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": s_email,
            "full_name": "Aluno Desativado",
            "password": "password123",
            "role": OrgRole.STUDENT.value,
        },
    )
    # Desativa o aluno
    await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{s_id}/status",
        headers=tenant.owner.auth_headers,
        json={"is_active": False},
    )

    # Act & Assert: 1. Filtro por papel (role=teacher)
    res_role = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members?role=teacher",
        headers=tenant.owner.auth_headers,
    )
    assert res_role.status_code == 200
    teachers = res_role.json()
    assert all(m["role"] == "teacher" for m in teachers)
    assert any(m["user_id"] == str(t_id) for m in teachers)

    # Act & Assert: 2. Filtro por status (is_active=false)
    res_inactive = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members?is_active=false",
        headers=tenant.owner.auth_headers,
    )
    assert res_inactive.status_code == 200
    inactives = res_inactive.json()
    assert any(m["user_id"] == str(s_id) for m in inactives)

    # Act & Assert: 3. Busca por texto (search por nome)
    res_search_name = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members?search=filtro",
        headers=tenant.owner.auth_headers,
    )
    assert res_search_name.status_code == 200
    assert any(m["user_id"] == str(t_id) for m in res_search_name.json())

    # Act & Assert: 4. Busca por texto (search por email)
    res_search_email = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members?search={s_email}",
        headers=tenant.owner.auth_headers,
    )
    assert res_search_email.status_code == 200
    assert len(res_search_email.json()) == 1
    assert res_search_email.json()[0]["user_id"] == str(s_id)

    # Act & Assert: 5. Paginação (limit e offset)
    res_paged = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members?limit=1&offset=0",
        headers=tenant.owner.auth_headers,
    )
    assert res_paged.status_code == 200
    assert len(res_paged.json()) == 1


@pytest.mark.asyncio
async def test_update_member_role_and_status_lifecycle(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Owner promove aluno para professor
    put_role = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/role",
        headers=tenant.owner.auth_headers,
        json={"role": OrgRole.TEACHER.value},
    )
    # Assert
    assert put_role.status_code == 200
    assert put_role.json()["role"] == OrgRole.TEACHER.value

    # Act: Owner desativa o membro
    patch_status = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/status",
        headers=tenant.owner.auth_headers,
        json={"is_active": False},
    )
    # Assert
    assert patch_status.status_code == 200
    assert patch_status.json()["is_active"] is False

    # Act: Membro desativado tenta acessar rota -> 403
    access_res = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.student.auth_headers,
    )
    # Assert
    assert access_res.status_code == 403


@pytest.mark.asyncio
async def test_member_role_and_status_edge_cases_and_rbac_violations(
    async_client: AsyncClient, tenant: TenantContext
):
    # 1. Tentativa de auto-desativação do Owner -> 400
    res_self = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.owner.user.id}/status",
        headers=tenant.owner.auth_headers,
        json={"is_active": False},
    )
    assert res_self.status_code == 400
    assert "próprio status" in res_self.json()["detail"].lower()

    # 2. Admin tenta desativar o Owner -> 400
    res_owner_deact = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.owner.user.id}/status",
        headers=tenant.admin.auth_headers,
        json={"is_active": False},
    )
    assert res_owner_deact.status_code == 400
    assert "proprietário" in res_owner_deact.json()["detail"].lower()

    # 3. Admin tenta alterar papel de outro Admin -> 403
    res_adm_demote = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.admin.user.id}/role",
        headers=tenant.admin.auth_headers,
        json={"role": OrgRole.TEACHER.value},
    )
    assert res_adm_demote.status_code == 403

    # 4. Tentativa de atribuir role=owner via endpoint de papel -> 400
    res_put_owner = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/role",
        headers=tenant.owner.auth_headers,
        json={"role": OrgRole.OWNER.value},
    )
    assert res_put_owner.status_code == 400

    # 5. Tentativa de alterar papel do próprio Owner -> 400
    res_mod_owner = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.owner.user.id}/role",
        headers=tenant.owner.auth_headers,
        json={"role": OrgRole.TEACHER.value},
    )
    assert res_mod_owner.status_code == 400

    # 6. Membro inexistente -> 404
    non_existent = uuid.uuid4()
    res_nf_role = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{non_existent}/role",
        headers=tenant.owner.auth_headers,
        json={"role": OrgRole.TEACHER.value},
    )
    assert res_nf_role.status_code == 404

    res_nf_status = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{non_existent}/status",
        headers=tenant.owner.auth_headers,
        json={"is_active": False},
    )
    assert res_nf_status.status_code == 404

    # 7. Tentativa de cadastrar membro diretamente com papel OWNER -> 400
    res_create_owner = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": "owner_direto@example.com",
            "full_name": "Owner Direto",
            "password": "password123",
            "role": OrgRole.OWNER.value,
        },
    )
    assert res_create_owner.status_code == 400
    assert "proprietário" in res_create_owner.json()["detail"].lower()

    # 8. Admin tenta promover um Aluno para ADMIN -> 403
    res_promote_admin = await async_client.put(
        f"/api/v1/orgs/{tenant.org.id}/members/{tenant.student.user.id}/role",
        headers=tenant.admin.auth_headers,
        json={"role": OrgRole.ADMIN.value},
    )
    assert res_promote_admin.status_code == 403
    assert "proprietário" in res_promote_admin.json()["detail"].lower()


@pytest.mark.asyncio
async def test_admin_cannot_deactivate_another_admin_should_return_403(
    async_client: AsyncClient, tenant: TenantContext, monkeypatch
) -> None:
    # Cria um segundo admin via Owner
    second_admin_id = uuid.uuid4()
    second_admin_email = f"second_admin_{second_admin_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={
                "id": second_admin_id,
                "email": second_admin_email,
                "full_name": "Second Admin",
            }
        ),
    )
    create_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/members",
        headers=tenant.owner.auth_headers,
        json={
            "email": second_admin_email,
            "full_name": "Second Admin",
            "password": "password123",
            "role": OrgRole.ADMIN.value,
        },
    )
    assert create_res.status_code == 201

    # Primeiro Admin tenta desativar o segundo Admin -> 403
    res_deact = await async_client.patch(
        f"/api/v1/orgs/{tenant.org.id}/members/{second_admin_id}/status",
        headers=tenant.admin.auth_headers,
        json={"is_active": False},
    )
    assert res_deact.status_code == 403
    assert "proprietário" in res_deact.json()["detail"].lower()
