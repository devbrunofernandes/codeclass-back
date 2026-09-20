import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User


async def setup_test_environment(db_session: AsyncSession) -> dict[str, Any]:
    """Cria uma organização base com Owner, Admin, Teacher e Student."""
    owner_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    other_teacher_id = uuid.uuid4()
    other_student_id = uuid.uuid4()

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
        full_name="Student User",
    )
    other_teacher = User(
        id=other_teacher_id,
        email=f"oteacher_{other_teacher_id.hex[:6]}@test.com",
        full_name="Other Teacher",
    )
    other_student = User(
        id=other_student_id,
        email=f"ostudent_{other_student_id.hex[:6]}@test.com",
        full_name="Other Student",
    )

    org = Organization(
        id=uuid.uuid4(),
        name="Org Teste",
        slug=f"org-test-{owner_id.hex[:6]}",
        owner_id=owner_id,
    )

    db_session.add_all(
        [owner, admin, teacher, student, other_teacher, other_student, org]
    )
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
            organization_id=org.id, user_id=other_teacher_id, role=OrgRole.TEACHER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=other_student_id, role=OrgRole.STUDENT
        ),
    ]
    db_session.add_all(members)
    await db_session.commit()

    return {
        "org": org,
        "owner": owner,
        "admin": admin,
        "teacher": teacher,
        "student": student,
        "other_teacher": other_teacher,
        "other_student": other_student,
    }


@pytest.mark.asyncio
async def test_create_classroom_by_teacher(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)
    token = create_access_token(user_id=env["teacher"].id)

    payload = {
        "name": "Turma de Algoritmos",
        "description": "Estruturas de Dados Avançadas",
    }
    response = await async_client.post(
        f"/api/v1/orgs/{env['org'].id}/classrooms",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Turma de Algoritmos"
    assert data["description"] == "Estruturas de Dados Avançadas"
    assert data["teacher_id"] == str(env["teacher"].id)
    assert data["organization_id"] == str(env["org"].id)


@pytest.mark.asyncio
async def test_create_classroom_by_admin_and_owner(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)
    admin_token = create_access_token(user_id=env["admin"].id)
    owner_token = create_access_token(user_id=env["owner"].id)

    # Admin cria indicando o professor
    payload_admin = {
        "name": "Turma Admin",
        "description": "Criada pelo admin",
        "teacher_id": str(env["teacher"].id),
    }
    res_admin = await async_client.post(
        f"/api/v1/orgs/{env['org'].id}/classrooms",
        json=payload_admin,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 201
    assert res_admin.json()["teacher_id"] == str(env["teacher"].id)

    # Owner cria indicando o professor
    payload_owner = {
        "name": "Turma Owner",
        "description": "Criada pelo owner",
        "teacher_id": str(env["other_teacher"].id),
    }
    res_owner = await async_client.post(
        f"/api/v1/orgs/{env['org'].id}/classrooms",
        json=payload_owner,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner.status_code == 201
    assert res_owner.json()["teacher_id"] == str(env["other_teacher"].id)


@pytest.mark.asyncio
async def test_create_classroom_forbidden_for_student(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)
    student_token = create_access_token(user_id=env["student"].id)

    payload = {"name": "Turma Inválida"}
    response = await async_client.post(
        f"/api/v1/orgs/{env['org'].id}/classrooms",
        json=payload,
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_my_classes(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)

    # Cria 2 salas
    c1 = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["teacher"].id,
        name="Algoritmos I",
    )
    c2 = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["other_teacher"].id,
        name="Banco de Dados",
    )
    db_session.add_all([c1, c2])
    await db_session.flush()

    # Matricula o student na sala c1
    enrollment = ClassroomStudent(classroom_id=c1.id, student_id=env["student"].id)
    db_session.add(enrollment)
    await db_session.commit()

    # Professor 1 deve ver c1
    t1_token = create_access_token(user_id=env["teacher"].id)
    res_t1 = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers={"Authorization": f"Bearer {t1_token}"},
    )
    assert res_t1.status_code == 200
    classes_t1 = res_t1.json()
    assert len(classes_t1) == 1
    assert classes_t1[0]["id"] == str(c1.id)
    assert classes_t1[0]["role_in_class"] == "teacher"

    # Aluno deve ver c1
    s_token = create_access_token(user_id=env["student"].id)
    res_s = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers={"Authorization": f"Bearer {s_token}"},
    )
    assert res_s.status_code == 200
    classes_s = res_s.json()
    assert len(classes_s) == 1
    assert classes_s[0]["id"] == str(c1.id)
    assert classes_s[0]["role_in_class"] == "student"


@pytest.mark.asyncio
async def test_get_classroom_details(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)

    classroom = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["teacher"].id,
        name="Compiladores",
        description="Construção de Compiladores",
    )
    db_session.add(classroom)
    await db_session.flush()

    enrollment = ClassroomStudent(
        classroom_id=classroom.id, student_id=env["student"].id
    )
    db_session.add(enrollment)
    await db_session.commit()

    teacher_token = create_access_token(user_id=env["teacher"].id)
    student_token = create_access_token(user_id=env["student"].id)
    other_student_token = create_access_token(user_id=env["other_student"].id)

    # Professor da turma acessa
    res = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Compiladores"
    assert data["teacher"]["id"] == str(env["teacher"].id)
    assert data["total_students"] == 1

    # Aluno matriculado acessa
    res_s = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_s.status_code == 200

    # Aluno não matriculado é barrado com 403
    res_other = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}",
        headers={"Authorization": f"Bearer {other_student_token}"},
    )
    assert res_other.status_code == 403


@pytest.mark.asyncio
async def test_patch_classroom(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)

    classroom = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["teacher"].id,
        name="Nome Antigo",
    )
    db_session.add(classroom)
    await db_session.commit()

    teacher_token = create_access_token(user_id=env["teacher"].id)
    owner_token = create_access_token(user_id=env["owner"].id)
    other_teacher_token = create_access_token(user_id=env["other_teacher"].id)
    student_token = create_access_token(user_id=env["student"].id)

    # Outro professor não pode editar -> 403
    res_fail = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Tentativa Invalida"},
        headers={"Authorization": f"Bearer {other_teacher_token}"},
    )
    assert res_fail.status_code == 403

    # Aluno não pode editar -> 403
    res_fail_student = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Tentativa Aluno"},
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_fail_student.status_code == 403

    # Professor da turma pode editar
    res_ok = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Nome Atualizado pelo Docente"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["name"] == "Nome Atualizado pelo Docente"

    # Owner tem permissão total para editar
    res_owner = await async_client.patch(
        f"/api/v1/classrooms/{classroom.id}",
        json={"name": "Nome Atualizado pelo Owner"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_owner.status_code == 200
    assert res_owner.json()["name"] == "Nome Atualizado pelo Owner"


@pytest.mark.asyncio
async def test_delete_classroom(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_test_environment(db_session)

    c1 = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["teacher"].id,
        name="Para Deletar",
    )
    c2 = Classroom(
        id=uuid.uuid4(),
        organization_id=env["org"].id,
        teacher_id=env["teacher"].id,
        name="Para Deletar pelo Owner",
    )
    db_session.add_all([c1, c2])
    await db_session.commit()

    teacher_token = create_access_token(user_id=env["teacher"].id)
    owner_token = create_access_token(user_id=env["owner"].id)
    student_token = create_access_token(user_id=env["student"].id)

    # Aluno não pode excluir
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{c1.id}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_fail.status_code == 403

    # Professor da turma exclui
    res_t = await async_client.delete(
        f"/api/v1/classrooms/{c1.id}",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_t.status_code == 204

    # Owner exclui com permissões totais
    res_o = await async_client.delete(
        f"/api/v1/classrooms/{c2.id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_o.status_code == 204
