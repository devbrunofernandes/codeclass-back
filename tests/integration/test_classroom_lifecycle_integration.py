import io
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.assignment import Assignment
from app.models.chat import ClassroomMessage
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import (
    AssignmentType,
    OrgRole,
    ReleasePolicyType,
    SubmissionStatus,
)
from app.models.organization import Organization, OrganizationMember
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
    SubmissionEvaluation,
)
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
    replacement_teacher_id = uuid.uuid4()
    replacement_teacher = User(
        id=replacement_teacher_id,
        email="replacement_teacher_lifecycle@test.com",
        full_name="Prof. Ada",
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
    db_session.add_all([owner, teacher, replacement_teacher, student, org])
    await db_session.flush()

    members = [
        OrganizationMember(
            organization_id=org.id, user_id=owner_id, role=OrgRole.OWNER
        ),
        OrganizationMember(
            organization_id=org.id, user_id=teacher_id, role=OrgRole.TEACHER
        ),
        OrganizationMember(
            organization_id=org.id,
            user_id=replacement_teacher_id,
            role=OrgRole.TEACHER,
        ),
        OrganizationMember(
            organization_id=org.id, user_id=student_id, role=OrgRole.STUDENT
        ),
    ]
    db_session.add_all(members)
    await db_session.commit()

    owner_token = create_access_token(user_id=owner_id)
    teacher_token = create_access_token(user_id=teacher_id)
    replacement_teacher_token = create_access_token(user_id=replacement_teacher_id)
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

    # Registros pedagógicos e mensagens existentes devem sobreviver à transferência.
    assignment = Assignment(
        classroom_id=uuid.UUID(classroom_id),
        title="Atividade preservada",
        description="Conteúdo existente",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={"language": "python"},
    )
    db_session.add(assignment)
    await db_session.flush()
    submission = Submission(
        assignment_id=assignment.id,
        student_id=student_id,
        content={"source_code": "print('ok')"},
        status=SubmissionStatus.PUBLISHED,
    )
    db_session.add(submission)
    await db_session.flush()
    insight = SubmissionAiInsight(
        submission_id=submission.id,
        status="completed",
        reasoning="Insight existente",
    )
    evaluation = SubmissionEvaluation(
        submission_id=submission.id,
        grade=9,
        general_feedback="Avaliação existente",
    )
    message = ClassroomMessage(
        classroom_id=uuid.UUID(classroom_id),
        sender_id=teacher_id,
        content="Mensagem existente",
    )
    db_session.add_all([insight, evaluation, message])
    await db_session.commit()

    # 8. Coordenação troca o responsável preservando matrícula e acesso pedagógico
    transfer_res = await async_client.put(
        f"/api/v1/classrooms/{classroom_id}/teacher",
        json={"teacher_id": str(replacement_teacher_id)},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert transfer_res.status_code == 200
    assert transfer_res.json()["teacher_id"] == str(replacement_teacher_id)
    async with async_session_maker() as verify_session:
        persisted_classroom = await verify_session.get(
            Classroom, uuid.UUID(classroom_id)
        )
        assert persisted_classroom is not None
        assert persisted_classroom.teacher_id == replacement_teacher_id
        assert persisted_classroom.name == "Programação Web Avançada"
        persisted_enrollment = await verify_session.scalar(
            select(ClassroomStudent).where(
                ClassroomStudent.classroom_id == uuid.UUID(classroom_id),
                ClassroomStudent.student_id == student_id,
            )
        )
        assert persisted_enrollment is not None
        persisted_assignment = await verify_session.get(Assignment, assignment.id)
        assert persisted_assignment is not None
        assert persisted_assignment.title == "Atividade preservada"
        persisted_submission = await verify_session.get(Submission, submission.id)
        assert persisted_submission is not None
        assert persisted_submission.content == {"source_code": "print('ok')"}
        assert await verify_session.get(SubmissionAiInsight, insight.id) is not None
        persisted_evaluation = await verify_session.get(
            SubmissionEvaluation, evaluation.id
        )
        assert persisted_evaluation is not None
        assert persisted_evaluation.grade == 9
        persisted_message = await verify_session.get(ClassroomMessage, message.id)
        assert persisted_message is not None
        assert persisted_message.content == "Mensagem existente"
    down_after_transfer = await async_client.get(
        f"/api/v1/classrooms/{classroom_id}/attachments/ementa.pdf/download",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert down_after_transfer.status_code == 200

    former_teacher_res = await async_client.patch(
        f"/api/v1/classrooms/{classroom_id}",
        json={"name": "Edição pelo docente anterior"},
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert former_teacher_res.status_code == 403
    replacement_teacher_res = await async_client.patch(
        f"/api/v1/classrooms/{classroom_id}",
        json={"name": "Turma após transferência"},
        headers={"Authorization": f"Bearer {replacement_teacher_token}"},
    )
    assert replacement_teacher_res.status_code == 200
    assert replacement_teacher_res.json()["name"] == "Turma após transferência"

    # 9. Owner remove a turma após verificar o ciclo de transferência
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


@pytest.mark.asyncio
async def test_batch_enrollment_lifecycle_should_persist_and_remove_all(
    async_client, tenant, classroom
):
    ids = [tenant.student.user.id, tenant.other_student.user.id]
    url = f"/api/v1/classrooms/{classroom.id}/students/batch"
    response = await async_client.post(
        url,
        json={"student_ids": [str(i) for i in ids]},
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 201
    async with async_session_maker() as session:
        for student_id in ids:
            assert (
                await session.get(ClassroomStudent, (classroom.id, student_id))
                is not None
            )
    for student_id in ids:
        response = await async_client.delete(
            f"/api/v1/classrooms/{classroom.id}/students/{student_id}",
            headers=tenant.teacher.auth_headers,
        )
        assert response.status_code == 204
    async with async_session_maker() as session:
        for student_id in ids:
            assert (
                await session.get(ClassroomStudent, (classroom.id, student_id)) is None
            )
