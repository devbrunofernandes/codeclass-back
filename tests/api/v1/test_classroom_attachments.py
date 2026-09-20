import io
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.services.storage_service import StorageError, storage_service


async def setup_attachment_environment(db_session: AsyncSession) -> dict[str, Any]:
    owner_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
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
    other_student = User(
        id=other_student_id,
        email=f"ostudent_{other_student_id.hex[:6]}@test.com",
        full_name="Other Student",
    )

    org = Organization(
        id=uuid.uuid4(),
        name="Org Anexos",
        slug=f"org-att-{owner_id.hex[:6]}",
        owner_id=owner_id,
    )

    db_session.add_all([owner, admin, teacher, student, other_student, org])
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
            organization_id=org.id, user_id=other_student_id, role=OrgRole.STUDENT
        ),
    ]
    db_session.add_all(members)

    classroom = Classroom(
        id=uuid.uuid4(),
        organization_id=org.id,
        teacher_id=teacher_id,
        name="Turma Anexos",
    )
    db_session.add(classroom)
    await db_session.flush()

    enrollment = ClassroomStudent(classroom_id=classroom.id, student_id=student_id)
    db_session.add(enrollment)
    await db_session.commit()

    return {
        "org": org,
        "owner": owner,
        "admin": admin,
        "teacher": teacher,
        "student": student,
        "other_student": other_student,
        "classroom": classroom,
    }


@pytest.mark.asyncio
async def test_upload_attachment_teacher_and_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
    create_access_token,
    monkeypatch,
):
    env = await setup_attachment_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)
    owner_token = create_access_token(user_id=env["owner"].id)

    mock_upload = AsyncMock(
        return_value={
            "file_name": "slides.pdf",
            "file_path": f"{env['org'].id}/{env['classroom'].id}/slides.pdf",
            "size_bytes": 1024,
            "content_type": "application/pdf",
        }
    )
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload)

    # Professor envia anexo
    files = {
        "file": ("slides.pdf", io.BytesIO(b"%PDF-1.4 dummy content"), "application/pdf")
    }
    res_t = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        files=files,
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_t.status_code == 201
    assert res_t.json()["file_name"] == "slides.pdf"

    # Owner também pode enviar anexo com suas permissões totais
    files_owner = {"file": ("dataset.csv", io.BytesIO(b"id,val\n1,2"), "text/csv")}
    mock_upload_owner = AsyncMock(
        return_value={
            "file_name": "dataset.csv",
            "file_path": f"{env['org'].id}/{env['classroom'].id}/dataset.csv",
            "size_bytes": 12,
            "content_type": "text/csv",
        }
    )
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload_owner)
    res_o = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        files=files_owner,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res_o.status_code == 201


@pytest.mark.asyncio
async def test_upload_attachment_forbidden_for_student(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_attachment_environment(db_session)
    student_token = create_access_token(user_id=env["student"].id)

    files = {"file": ("hack.exe", io.BytesIO(b"dummy"), "application/octet-stream")}
    res = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        files=files,
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_upload_attachment_too_large(
    async_client: AsyncClient,
    db_session: AsyncSession,
    create_access_token,
    monkeypatch,
):
    env = await setup_attachment_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)

    mock_upload = AsyncMock(
        side_effect=StorageError(
            "Tamanho do arquivo excede o limite máximo permitido de 30MB.",
            status_code=413,
        )
    )
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload)

    files = {
        "file": ("large.iso", io.BytesIO(b"huge content"), "application/octet-stream")
    }
    res = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        files=files,
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res.status_code == 413


@pytest.mark.asyncio
async def test_list_and_download_attachments(
    async_client: AsyncClient,
    db_session: AsyncSession,
    create_access_token,
    monkeypatch,
):
    env = await setup_attachment_environment(db_session)
    student_token = create_access_token(user_id=env["student"].id)
    other_student_token = create_access_token(user_id=env["other_student"].id)

    mock_list = AsyncMock(
        return_value=[
            {
                "file_name": "guia.pdf",
                "file_path": f"{env['org'].id}/{env['classroom'].id}/guia.pdf",
                "size_bytes": 2048,
                "content_type": "application/pdf",
                "uploaded_at": "2026-09-20T12:00:00Z",
            }
        ]
    )
    monkeypatch.setattr(storage_service, "list_classroom_materials", mock_list)

    mock_signed_url = AsyncMock(
        return_value="https://supabase.co/storage/v1/object/sign/classroom-materials/guia.pdf?token=xyz"
    )
    monkeypatch.setattr(storage_service, "create_signed_download_url", mock_signed_url)

    # Aluno matriculado lista materiais
    res_list = await async_client.get(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_list.status_code == 200
    files = res_list.json()
    assert len(files) == 1
    assert files[0]["file_name"] == "guia.pdf"

    # Aluno matriculado gera signed URL para download
    res_down = await async_client.get(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments/guia.pdf/download",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_down.status_code == 200
    assert "download_url" in res_down.json()
    assert "token=xyz" in res_down.json()["download_url"]

    # Aluno de fora da sala é bloqueado com 403
    res_fail = await async_client.get(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        headers={"Authorization": f"Bearer {other_student_token}"},
    )
    assert res_fail.status_code == 403


@pytest.mark.asyncio
async def test_delete_attachment(
    async_client: AsyncClient,
    db_session: AsyncSession,
    create_access_token,
    monkeypatch,
):
    env = await setup_attachment_environment(db_session)
    teacher_token = create_access_token(user_id=env["teacher"].id)
    student_token = create_access_token(user_id=env["student"].id)

    mock_delete = AsyncMock(return_value=None)
    monkeypatch.setattr(storage_service, "delete_classroom_material", mock_delete)

    # Aluno não pode deletar
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments/slides.pdf",
        headers={"Authorization": f"Bearer {student_token}"},
    )
    assert res_fail.status_code == 403

    # Professor da turma deleta
    res_ok = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments/slides.pdf",
        headers={"Authorization": f"Bearer {teacher_token}"},
    )
    assert res_ok.status_code == 204


@pytest.mark.asyncio
async def test_admin_cannot_upload_or_delete_attachment(
    async_client: AsyncClient, db_session: AsyncSession, create_access_token
):
    env = await setup_attachment_environment(db_session)
    admin_token = create_access_token(user_id=env["admin"].id)

    # Admin tenta fazer upload de anexo -> 403 Forbidden
    files = {"file": ("admin_notes.pdf", io.BytesIO(b"content"), "application/pdf")}
    res_upload = await async_client.post(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments",
        files=files,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_upload.status_code == 403

    # Admin tenta deletar anexo -> 403 Forbidden
    res_del = await async_client.delete(
        f"/api/v1/classrooms/{env['classroom'].id}/attachments/slides.pdf",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_del.status_code == 403
