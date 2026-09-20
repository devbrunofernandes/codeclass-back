import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User


async def setup_membership_environment(db_session: AsyncSession) -> dict[str, Any]:
    owner_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    student2_id = uuid.uuid4()

    owner = User(
        id=owner_id, email=f"owner_{owner_id.hex[:6]}@test.com", full_name="Owner User"
    )
    admin = User(
        id=admin_id, email=f"admin_{admin_id.hex[:6]}@test.com", full_name="Admin User"
    )
    teacher = User(
        id=teacher_id,
        email=f"teacher_{teacher_id.hex[:6]}@test.com",
        full_name="Teacher User",
    )
    student = User(
        id=student_id,
        email=f"student_{student_id.hex[:6]}@test.com",
        full_name="Student 1",
    )
    student2 = User(
        id=student2_id,
        email=f"student2_{student2_id.hex[:6]}@test.com",
        full_name="Student 2",
    )

    org = Organization(
        id=uuid.uuid4(),
        name="Org Membros",
        slug=f"org-mem-{owner_id.hex[:6]}",
        owner_id=owner_id,
    )

    db_session.add_all([owner, admin, teacher, student, student2, org])
    await db_session.flush()

    members = [
        OrganizationMember(
            organization_id=org.id, user_id=owner_id, role=OrgRole.OWNER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=admin_id, role=OrgRole.ADMIN
        ),
        OrganizationMember(
            organization_id=org.id, user_id=teacher_id, role=OrgRole.TEACHER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=student_id, role=OrgRole.STUDENT
        ),
        OrganizationMember(
            organization_id=org.id, user_id=student2_id, role=OrgRole.STUDENT
        ),
    ]
    db_session.add_all(members)

    classroom = Classroom(
        id=uuid.uuid4(),
        organization_id=org.id,
        teacher_id=teacher_id,
        name="Turma Membros",
    )
    db_session.add(classroom)
    await db_session.commit()

    return {
        "org": org,
        "owner": owner,
        "admin": admin,
        "teacher": teacher,
        "student": student,
        "student2": student2,
        "classroom": classroom,
    }


@pytest.mark.asyncio
async def test_enroll_student_success(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)

    # Professor matricula o aluno 1
    response = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(env["student"].id)},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["student_id"] == str(env["student"].id)
    assert data["full_name"] == "Student 1"

    # Owner matricula o aluno 2 com suas permissões totais
    owner_token = create_access_token(user_id=env["owner"].id)
    res_owner = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(env["student2"].id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner.status_code == 201
    assert res_owner.json()["student_id"] == str(env["student2"].id)


@pytest.mark.asyncio
async def test_enroll_student_duplicate_conflict(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)

    # Primeira matrícula
    await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(env["student"].id)},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )

    # Tentativa de matrícula duplicada -> 409 Conflict
    response = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(env["student"].id)},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_enroll_student_cross_tenant_forbidden(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)

    # Cria usuário de outra organização
    foreign_user_id = uuid.uuid4()
    foreign_user = User(
        id=foreign_user_id, email="foreign@test.com", full_name="Foreign Student"
    )
    foreign_org = Organization(
        id=uuid.uuid4(),
        name="Foreign Org",
        slug="foreign-org",
        owner_id=foreign_user_id,
    )
    db_session.add_all([foreign_user, foreign_org])
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=foreign_org.id,
            user_id=foreign_user_id,
            role=OrgRole.STUDENT,
        )
    )
    await db_session.commit()

    # Tentativa de matricular usuário de outra organização
    response = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(foreign_user_id)},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert response.status_code in (400, 404)


@pytest.mark.asyncio
async def test_get_classroom_members_and_alias(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)

    # Matricula student
    enrollment = ClassroomStudent(
        classroom_id=env["classroom"].id, student_id=env["student"].id
    )
    db_session.add(enrollment)
    await db_session.commit()

    teacher_token = create_access_token(user_id=env["teacher"].id)
    student_token = create_access_token(user_id=env["student"].id)

    # Teste via rota descritiva /members
    res_members = await async_client.get(
        f"/api/v1/classrooms/{env['classroom'].id}/members",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_members.status_code == 200
    data = res_members.json()
    assert data["teacher"]["id"] == str(env["teacher"].id)
    assert len(data["students"]) == 1
    assert data["students"][0]["student_id"] == str(env["student"].id)

    # Teste via rota alias /students para retrocompatibilidade
    res_students = await async_client.get(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_students.status_code == 200
    data_students = res_students.json()
    assert data_students["teacher"]["id"] == str(env["teacher"].id)
    assert len(data_students["students"]) == 1


@pytest.mark.asyncio
async def test_delete_student_from_classroom(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)

    # Matricula o aluno
    enrollment = ClassroomStudent(
        classroom_id=env["classroom"].id, student_id=env["student"].id
    )
    db_session.add(enrollment)
    await db_session.commit()

    teacher_token = create_access_token(user_id=env["teacher"].id)
    student2_token = create_access_token(user_id=env["student2"].id)

    # Aluno tenta desmatricular outro -> 403
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/students/{env['student'].id}",
        headers={"Authorization": f"Bearer {student2_token}"},
    )
    assert res_fail.status_code == 403

    # Professor da turma desmatricula com sucesso -> 204
    res_ok = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/students/{env['student'].id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_ok.status_code == 204

    # Tentativa de remover novamente -> 404
    res_not_found = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/students/{env['student'].id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_not_found.status_code == 404


@pytest.mark.asyncio
async def test_enroll_teacher_as_student_fails(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_membership_environment(db_session)
    owner_token = create_access_token(user_id=env["owner"].id)

    # Tentar matricular o professor como aluno na turma
    response = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/students",
        json={"student_id": str(env["teacher"].id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert response.status_code == 400
    assert "Apenas membros com papel de estudante" in response.json()["detail"]
