import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_create_classroom_when_called_by_teacher_should_create_successfully(
    async_client: AsyncClient, tenant: TenantContext
):
    # Arrange
    payload = {
        "name": "Turma de Algoritmos",
        "description": "Estruturas de Dados Avançadas",
    }

    # Act
    response = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Turma de Algoritmos"
    assert data["teacher_id"] == str(tenant.teacher.user.id)
    assert data["organization_id"] == str(tenant.org.id)


@pytest.mark.asyncio
async def test_create_classroom_when_payload_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext
):
    # Arrange: payload sem o campo obrigatório 'name'
    payload = {"description": "Sem nome"}

    # Act
    response = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_classroom_when_unauthenticated_should_return_401(
    async_client: AsyncClient, tenant: TenantContext
):
    # Arrange
    payload = {"name": "Turma Não Autorizada"}

    # Act
    response = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json=payload,
    )

    # Assert
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_classroom_when_called_by_admin_or_owner_with_teacher_should_succeed(
    async_client: AsyncClient, tenant: TenantContext
):
    # Arrange & Act: Admin indicando docente
    res_admin = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={
            "name": "Turma Criada por Admin",
            "teacher_id": str(tenant.teacher.user.id),
        },
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 201
    assert res_admin.json()["teacher_id"] == str(tenant.teacher.user.id)

    # Arrange & Act: Owner indicando docente
    res_owner = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={
            "name": "Turma Criada por Owner",
            "teacher_id": str(tenant.teacher.user.id),
        },
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 201
    assert res_owner.json()["teacher_id"] == str(tenant.teacher.user.id)


@pytest.mark.asyncio
async def test_create_classroom_when_teacher_role_is_invalid_should_return_400(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act: Admin tenta indicar um aluno como professor da turma
    res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={
            "name": "Turma Docente Invalido",
            "teacher_id": str(tenant.student.user.id),
        },
        headers=tenant.admin.auth_headers,
    )

    # Assert
    assert res.status_code == 400
    assert "papel docente ou administrativo" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_classroom_when_student_attempts_creation_should_return_403(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act
    res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma Aluno"},
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_get_my_classrooms_strategy_pattern_should_return_correct_roles(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_classroom,
    db_session: AsyncSession,
):
    # Arrange: Turma 1 com professor 1 e aluno via factory
    c1 = await create_classroom(tenant, name="Algoritmos 1")
    await create_classroom(
        tenant, teacher_id=tenant.other_teacher.user.id, name="Algoritmos 2"
    )

    enrollment = ClassroomStudent(classroom_id=c1.id, student_id=tenant.student.user.id)
    db_session.add(enrollment)
    await db_session.commit()

    # Act & Assert: Professor 1 (Strategy Pattern -> role_in_class == teacher)
    res_t1 = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers=tenant.teacher.auth_headers,
    )
    assert res_t1.status_code == 200
    classes_t1 = res_t1.json()
    assert len(classes_t1) == 1
    assert classes_t1[0]["id"] == str(c1.id)
    assert classes_t1[0]["role_in_class"] == "teacher"

    # Act & Assert: Aluno (Strategy Pattern -> role_in_class == student)
    res_s = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers=tenant.student.auth_headers,
    )
    assert res_s.status_code == 200
    classes_s = res_s.json()
    assert len(classes_s) == 1
    assert classes_s[0]["id"] == str(c1.id)
    assert classes_s[0]["role_in_class"] == "student"

    # Act & Assert: Owner (Strategy Pattern -> role_in_class == owner para todas as turmas)
    res_owner = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 200
    classes_owner = res_owner.json()
    assert len(classes_owner) == 2
    assert all(c["role_in_class"] == "owner" for c in classes_owner)

    # Act & Assert: Admin (Strategy Pattern -> role_in_class == admin para todas as turmas)
    res_admin = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 200
    classes_admin = res_admin.json()
    assert len(classes_admin) == 2
    assert all(c["role_in_class"] == "admin" for c in classes_admin)


@pytest.mark.asyncio
async def test_get_classroom_details_rbac_and_isolation(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_tenant,
    classroom_with_student: Classroom,
):
    classroom = classroom_with_student

    # Act & Assert: Professor da turma acessa com sucesso (200)
    res_t = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_t.status_code == 200
    assert res_t.json()["name"] == classroom.name

    # Act & Assert: Aluno matriculado acessa com sucesso (200)
    res_s = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers=tenant.student.auth_headers,
    )
    assert res_s.status_code == 200

    # Act & Assert: Aluno não matriculado tem acesso negado (403)
    res_unrolled = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers=tenant.other_student.auth_headers,
    )
    assert res_unrolled.status_code == 403

    # Act & Assert: Multi-tenant (RNF01) - Usuário de outra organização recebe 403
    other_tenant = await create_tenant("Outra Org")
    res_cross_org = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers=other_tenant.owner.auth_headers,
    )
    assert res_cross_org.status_code == 403


@pytest.mark.asyncio
async def test_update_classroom_rbac_permissions(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):

    # Act & Assert: Outro docente não pode editar -> 403
    res_fail = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Tentativa Invalida"},
        headers=tenant.other_teacher.auth_headers,
    )
    assert res_fail.status_code == 403

    # Act & Assert: Aluno não pode editar -> 403
    res_fail_student = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Tentativa Aluno"},
        headers=tenant.student.auth_headers,
    )
    assert res_fail_student.status_code == 403

    # Act & Assert: Professor da turma pode editar -> 200
    res_ok = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Nome Atualizado pelo Docente"},
        headers=tenant.teacher.auth_headers,
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["name"] == "Nome Atualizado pelo Docente"

    # Act & Assert: Owner tem permissão total para editar -> 200
    res_owner = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Nome Atualizado pelo Owner"},
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 200
    assert res_owner.json()["name"] == "Nome Atualizado pelo Owner"


@pytest.mark.asyncio
async def test_delete_classroom_rbac_permissions(
    async_client: AsyncClient, tenant: TenantContext, create_classroom
):
    # Arrange via factory
    c1 = await create_classroom(tenant, name="Para Deletar")
    c2 = await create_classroom(tenant, name="Para Deletar pelo Owner")

    # Act & Assert: Aluno não pode excluir -> 403
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{c1.id}",
        headers=tenant.student.auth_headers,
    )
    assert res_fail.status_code == 403

    # Act & Assert: Professor da turma exclui -> 204
    res_t = await async_client.delete(
        f"/api/v1/classrooms/{c1.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_t.status_code == 204

    # Act & Assert: Owner exclui com permissões totais -> 204
    res_o = await async_client.delete(
        f"/api/v1/classrooms/{c2.id}",
        headers=tenant.owner.auth_headers,
    )
    assert res_o.status_code == 204


@pytest.mark.asyncio
async def test_classroom_edge_cases_and_not_found_should_return_404(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    random_id = uuid.uuid4()

    # 1. Buscar detalhes de sala inexistente -> 404
    res_not_found = await async_client.get(
        f"/api/v1/classrooms/{random_id}",
        headers=tenant.owner.auth_headers,
    )
    assert res_not_found.status_code == 404

    # 2. Atualizar sala inexistente -> 404
    res_patch_nf = await async_client.patch(
        f"/api/v1/classrooms/{random_id}",
        json={"name": "Novo Nome"},
        headers=tenant.owner.auth_headers,
    )
    assert res_patch_nf.status_code == 404

    # 3. Deletar sala inexistente -> 404
    res_del_nf = await async_client.delete(
        f"/api/v1/classrooms/{random_id}",
        headers=tenant.owner.auth_headers,
    )
    assert res_del_nf.status_code == 404

    # 4. Testar desmatrícula de aluno não matriculado -> 404
    res_unenroll_nf = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_unenroll_nf.status_code == 404

    # 5. Desmatrícula em sala inexistente -> 404
    res_unenroll_cls_nf = await async_client.delete(
        f"/api/v1/classrooms/{random_id}/students/{tenant.student.user.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_unenroll_cls_nf.status_code == 404
