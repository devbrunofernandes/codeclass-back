import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_enroll_student_when_valid_should_enroll_successfully(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange & Act: Professor da turma matricula o aluno 1
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["student_id"] == str(tenant.student.user.id)
    assert data["full_name"] == tenant.student.user.full_name

    # Arrange & Act: Owner matricula outro aluno com permissões totais
    res_owner = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.other_student.user.id)},
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
    )
    assert res_owner.status_code == 201
    assert res_owner.json()["student_id"] == str(tenant.other_student.user.id)


@pytest.mark.asyncio
async def test_enroll_student_when_payload_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Act: Envia student_id malformado
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": "not-a-valid-uuid"},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )

    # Assert
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_enroll_student_when_already_enrolled_should_return_409_conflict(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange: Primeira matrícula
    await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )

    # Act: Tentativa de matrícula duplicada
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )

    # Assert
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_enroll_student_when_cross_tenant_should_return_error(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    create_tenant,
):
    # Arrange: Cria aluno em outro tenant
    other_tenant = await create_tenant("Outro Tenant")

    # Act: Tenta matricular usuário do outro tenant
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(other_tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )

    # Assert
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_enroll_student_when_member_is_not_student_role_should_return_400(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Act: Tentar matricular o próprio professor como aluno
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.teacher.user.id)},
        headers={"Authorization": f"Bearer {tenant.owner.token}"},
    )

    # Assert
    assert response.status_code == 400
    assert "Apenas membros com papel de estudante" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_classroom_members_and_alias_endpoints_should_return_members_list(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    db_session: AsyncSession,
):
    # Arrange: Matricula student
    enrollment = ClassroomStudent(
        classroom_id=classroom.id, student_id=tenant.student.user.id
    )
    db_session.add(enrollment)
    await db_session.commit()

    # Act & Assert: Via rota descritiva /members
    res_members = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/members",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert res_members.status_code == 200
    data = res_members.json()
    assert data["teacher"]["id"] == str(tenant.teacher.user.id)
    assert len(data["students"]) == 1
    assert data["students"][0]["student_id"] == str(tenant.student.user.id)

    # Act & Assert: Via rota alias /students para retrocompatibilidade
    res_students = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/students",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert res_students.status_code == 200
    data_students = res_students.json()
    assert data_students["teacher"]["id"] == str(tenant.teacher.user.id)
    assert len(data_students["students"]) == 1


@pytest.mark.asyncio
async def test_delete_student_from_classroom_rbac_and_removal(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    db_session: AsyncSession,
):
    # Arrange: Matricula aluno
    enrollment = ClassroomStudent(
        classroom_id=classroom.id, student_id=tenant.student.user.id
    )
    db_session.add(enrollment)
    await db_session.commit()

    # Act & Assert: Outro aluno tenta desmatricular -> 403
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers={"Authorization": f"Bearer {tenant.other_student.token}"},
    )
    assert res_fail.status_code == 403

    # Act & Assert: Professor da turma desmatricula com sucesso -> 204
    res_ok = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert res_ok.status_code == 204

    # Act & Assert: Tentativa de remover novamente -> 404
    res_not_found = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert res_not_found.status_code == 404
