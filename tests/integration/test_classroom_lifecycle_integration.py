import io
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.services.storage_service import storage_service


@pytest.mark.asyncio
async def test_full_classroom_lifecycle(
    async_client: AsyncClient,
    db_session: AsyncSession,
    create_access_token,
    monkeypatch,
):
    # 1. Configura Organização e Usuários
    owner_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()

    owner = User(id=owner_id, email="owner_lifecycle@test.com", full_name="Owner Full")
    teacher = User(
        id=teacher_id, email="teacher_lifecycle@test.com", full_name="Prof. Silva"
    )
    student = User(
        id=student_id, email="student_lifecycle@test.com", full_name="Aluno João"
    )

    org = Organization(
        id=uuid.uuid4(),
        name="Tech Academy",
        slug="tech-academy",
        owner_id=owner_id,
    )
    db_session.add_all([owner, teacher, student, org])
    await db_session.flush()

    members = [
        OrganizationMember(
            organization_id=org.id, user_id=owner_id, role=OrgRole.OWNER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=teacher_id, role=OrgRole.TEACHER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=student_id, role=OrgRole.STUDENT
        ),
    ]
    db_session.add_all(members)
    await db_session.commit()

    owner_token = create_access_token(user_id=owner_id)
    teacher_token = create_access_token(user_id=teacher_id)
    student_token = create_access_token(user_id=student_id)

    # 2. Professor cria sala de aula
    create_res = await async_client.post(
        f"/api/v1/orgs/{org.id}/classrooms",
        json={"name": "Programação Web", "description": "FastAPI e React"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert create_res.status_code == 201
    classroom_data = create_res.json()
    classroom_id = classroom_data["id"]
    assert classroom_data["teacher_id"] == str(teacher_id)

    # 3. Professor matricula o aluno na sala
    enroll_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(student_id)},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert enroll_res.status_code == 201
    assert enroll_res.json()["student_id"] == str(student_id)

    # 4. Aluno consulta 'my-classes' e vê a turma
    my_classes_res = await async_client.get(
        "/api/v1/classrooms/my-classes",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert my_classes_res.status_code == 200
    my_classes = my_classes_res.json()
    assert len(my_classes) == 1
    assert my_classes[0]["id"] == classroom_id
    assert my_classes[0]["role_in_class"] == "student"

    # 5. Aluno consulta detalhes e membros da sala
    detail_res = await async_client.get(
        f"/api/v1/classrooms/{classroom_id}",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["total_students"] == 1
    assert detail_res.json()["teacher"]["full_name"] == "Prof. Silva"

    members_res = await async_client.get(
        f"/api/v1/classrooms/{classroom_id}/members",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert members_res.status_code == 200
    members_data = members_res.json()
    assert members_data["teacher"]["id"] == str(teacher_id)
    assert len(members_data["students"]) == 1
    assert members_data["students"][0]["full_name"] == "Aluno João"

    # 6. Upload e download de material com mocks do storage
    mock_upload = AsyncMock(
        return_value={
            "file_name": "ementa.pdf",
            "file_path": f"{org.id}/{classroom_id}/ementa.pdf",
            "size_bytes": 500,
            "content_type": "application/pdf",
        }
    )
    mock_signed = AsyncMock(return_value="https://supabase.co/sign/ementa.pdf")
    mock_delete = AsyncMock(return_value=None)
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload)
    monkeypatch.setattr(storage_service, "create_signed_download_url", mock_signed)
    monkeypatch.setattr(storage_service, "delete_classroom_material", mock_delete)

    files = {"file": ("ementa.pdf", io.BytesIO(b"%PDF dummy"), "application/pdf")}
    upload_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/attachments",
        files=files,
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert upload_res.status_code == 201

    down_res = await async_client.get(
        f"/api/v1/classrooms/{classroom_id}/attachments/ementa.pdf/download",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert down_res.status_code == 200
    assert down_res.json()["download_url"] == "https://supabase.co/sign/ementa.pdf"

    # 7. Owner utiliza permissões totais para editar, remover anexo e deletar a turma
    patch_res = await async_client.patch(
        f"/api/v1/classrooms/{classroom_id}",
        json={"name": "Programação Web Avançada"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Programação Web Avançada"

    del_att_res = await async_client.delete(
        f"/api/v1/classrooms/{classroom_id}/attachments/ementa.pdf",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_att_res.status_code == 204

    del_class_res = await async_client.delete(
        f"/api/v1/classrooms/{classroom_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert del_class_res.status_code == 204

    # 8. Verifica se a sala e matrículas foram removidas do banco
    res_db = await db_session.execute(
        select(Classroom).where(Classroom.id == uuid.UUID(classroom_id))
    )
    assert res_db.scalar_one_or_none() is None
    res_enrolled = await db_session.execute(
        select(ClassroomStudent).where(
            ClassroomStudent.classroom_id == uuid.UUID(classroom_id)
        )
    )
    assert res_enrolled.scalars().all() == []
