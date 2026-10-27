import pytest
from httpx import AsyncClient

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
        headers=tenant.teacher.auth_headers,
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
        headers=tenant.owner.auth_headers,
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
        headers=tenant.teacher.auth_headers,
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
        headers=tenant.teacher.auth_headers,
    )

    # Act: Tentativa de matrícula duplicada
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
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
        headers=tenant.teacher.auth_headers,
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
        headers=tenant.owner.auth_headers,
    )

    # Assert
    assert response.status_code == 400
    assert "Apenas membros com papel de estudante" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_classroom_members_and_alias_endpoints_should_return_members_list(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    enrolled_student: ClassroomStudent,
):
    # Act & Assert: Via rota descritiva /members
    res_members = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/members",
        headers=tenant.teacher.auth_headers,
    )
    assert res_members.status_code == 200
    data = res_members.json()
    assert data["teacher"]["id"] == str(tenant.teacher.user.id)
    assert len(data["students"]) == 1
    assert data["students"][0]["student_id"] == str(tenant.student.user.id)

    # Act & Assert: Via rota alias /students para retrocompatibilidade
    res_students = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/students",
        headers=tenant.student.auth_headers,
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
    enrolled_student: ClassroomStudent,
):
    # Act & Assert: Outro aluno tenta desmatricular -> 403
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers=tenant.other_student.auth_headers,
    )
    assert res_fail.status_code == 403

    # Act & Assert: Professor da turma desmatricula com sucesso -> 204
    res_ok = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_ok.status_code == 204

    # Act & Assert: Tentativa de remover novamente -> 404
    res_not_found = await async_client.delete(
        f"/api/v1/classrooms/{classroom.id}/students/{tenant.student.user.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_not_found.status_code == 404


@pytest.mark.asyncio
async def test_enroll_batch_when_valid_should_create_all(
    async_client, tenant, classroom
):
    ids = [str(tenant.student.user.id), str(tenant.other_student.user.id)]
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json={"student_ids": ids},
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 201
    assert [item["student_id"] for item in response.json()] == ids


@pytest.mark.asyncio
async def test_enroll_batch_when_conflict_should_not_create_remaining(
    async_client, tenant, classroom, enrolled_student, db_session
):
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json={
            "student_ids": [
                str(tenant.student.user.id),
                str(tenant.other_student.user.id),
            ]
        },
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 409
    assert (
        await db_session.get(
            ClassroomStudent, (classroom.id, tenant.other_student.user.id)
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"student_ids": []},
        {"student_ids": ["invalid"]},
        {"student_ids": ["00000000-0000-0000-0000-000000000001"] * 2},
        {"student_ids": ["00000000-0000-0000-0000-000000000001"] * 101},
    ],
)
async def test_enroll_batch_when_payload_invalid_should_return_422(
    async_client, tenant, classroom, payload
):
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_enroll_batch_when_unauthorized_should_reject(
    async_client, tenant, classroom
):
    url = f"/api/v1/classrooms/{classroom.id}/students/batch"
    payload = {"student_ids": [str(tenant.student.user.id)]}
    assert (await async_client.post(url, json=payload)).status_code == 401
    assert (
        await async_client.post(url, json=payload, headers=tenant.student.auth_headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_enroll_batch_when_invalid_member_should_leave_batch_unchanged(
    async_client, tenant, classroom, db_session, create_tenant
):
    other = await create_tenant("Outro lote")
    url = f"/api/v1/classrooms/{classroom.id}/students/batch"
    for invalid in [other.student.user.id, tenant.teacher.user.id]:
        response = await async_client.post(
            url,
            json={"student_ids": [str(tenant.student.user.id), str(invalid)]},
            headers=tenant.teacher.auth_headers,
        )
        assert response.status_code == 400
        assert (
            await db_session.get(
                ClassroomStudent, (classroom.id, tenant.student.user.id)
            )
            is None
        )


@pytest.mark.asyncio
async def test_enroll_batch_when_classroom_missing_or_forbidden_should_reject(
    async_client, tenant, classroom, create_tenant
):
    from uuid import uuid4

    payload = {"student_ids": [str(tenant.student.user.id)]}
    missing = await async_client.post(
        f"/api/v1/classrooms/{uuid4()}/students/batch",
        json=payload,
        headers=tenant.owner.auth_headers,
    )
    assert missing.status_code == 404
    wrong_teacher = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json=payload,
        headers=tenant.other_teacher.auth_headers,
    )
    assert wrong_teacher.status_code == 403
    other = await create_tenant("Outro tenant sala")
    other_tenant = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json=payload,
        headers=other.owner.auth_headers,
    )
    assert other_tenant.status_code in (403, 404)


@pytest.mark.asyncio
async def test_enroll_batch_when_student_inactive_should_not_enroll_any(
    async_client, tenant, classroom, db_session
):
    tenant.other_student.member.is_active = False
    await db_session.commit()
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/students/batch",
        json={
            "student_ids": [
                str(tenant.student.user.id),
                str(tenant.other_student.user.id),
            ]
        },
        headers=tenant.owner.auth_headers,
    )
    assert response.status_code == 400
    assert (
        await db_session.get(ClassroomStudent, (classroom.id, tenant.student.user.id))
        is None
    )
