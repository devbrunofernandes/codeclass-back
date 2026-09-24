import io
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.models.classroom import Classroom
from app.services.storage_service import StorageError, storage_service
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_upload_attachment_when_called_by_teacher_or_owner_should_succeed(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    monkeypatch,
):
    # Arrange: Mock do storage
    mock_upload = AsyncMock(
        return_value={
            "file_name": "slides.pdf",
            "file_path": f"{tenant.org.id}/{classroom_with_student.id}/slides.pdf",
            "size_bytes": 1024,
            "content_type": "application/pdf",
        }
    )
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload)

    # Act: Professor envia anexo
    files = {
        "file": ("slides.pdf", io.BytesIO(b"%PDF-1.4 dummy content"), "application/pdf")
    }
    res_t = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        files=files,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert res_t.status_code == 201
    assert res_t.json()["file_name"] == "slides.pdf"

    # Act & Assert: Owner envia anexo com permissão total
    files_owner = {"file": ("dataset.csv", io.BytesIO(b"id,val\n1,2"), "text/csv")}
    mock_upload_owner = AsyncMock(
        return_value={
            "file_name": "dataset.csv",
            "file_path": f"{tenant.org.id}/{classroom_with_student.id}/dataset.csv",
            "size_bytes": 12,
            "content_type": "text/csv",
        }
    )
    monkeypatch.setattr(storage_service, "upload_classroom_material", mock_upload_owner)
    res_o = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        files=files_owner,
        headers=tenant.owner.auth_headers,
    )
    assert res_o.status_code == 201


@pytest.mark.asyncio
async def test_upload_attachment_when_student_attempts_upload_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
):
    # Arrange
    files = {"file": ("hack.exe", io.BytesIO(b"dummy"), "application/octet-stream")}

    # Act
    res = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        files=files,
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_upload_attachment_when_file_exceeds_limit_should_return_413(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    monkeypatch,
):
    # Arrange
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

    # Act
    res = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        files=files,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert res.status_code == 413


@pytest.mark.asyncio
async def test_list_and_download_attachments_for_enrolled_student_should_succeed(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    monkeypatch,
):
    # Arrange
    mock_list = AsyncMock(
        return_value=[
            {
                "file_name": "guia.pdf",
                "file_path": f"{tenant.org.id}/{classroom_with_student.id}/guia.pdf",
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

    # Act & Assert: Aluno matriculado lista materiais -> 200
    res_list = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        headers=tenant.student.auth_headers,
    )
    assert res_list.status_code == 200
    files = res_list.json()
    assert len(files) == 1
    assert files[0]["file_name"] == "guia.pdf"

    # Act & Assert: Aluno matriculado gera signed URL -> 200
    res_down = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments/guia.pdf/download",
        headers=tenant.student.auth_headers,
    )
    assert res_down.status_code == 200
    assert "token=xyz" in res_down.json()["download_url"]

    # Act & Assert: Aluno não matriculado é bloqueado -> 403
    res_fail = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        headers=tenant.other_student.auth_headers,
    )
    assert res_fail.status_code == 403


@pytest.mark.asyncio
async def test_delete_attachment_rbac_permissions(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    monkeypatch,
):
    # Arrange
    mock_delete = AsyncMock(return_value=None)
    monkeypatch.setattr(storage_service, "delete_classroom_material", mock_delete)

    # Act & Assert: Aluno não pode deletar -> 403
    res_fail = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments/slides.pdf",
        headers=tenant.student.auth_headers,
    )
    assert res_fail.status_code == 403

    # Act & Assert: Professor da turma deleta -> 204
    res_ok = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments/slides.pdf",
        headers=tenant.teacher.auth_headers,
    )
    assert res_ok.status_code == 204


@pytest.mark.asyncio
async def test_admin_cannot_upload_or_delete_attachment_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
):
    # Act & Assert: Admin tenta upload -> 403
    files = {"file": ("admin_notes.pdf", io.BytesIO(b"content"), "application/pdf")}
    res_upload = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments",
        files=files,
        headers=tenant.admin.auth_headers,
    )
    assert res_upload.status_code == 403

    # Act & Assert: Admin tenta deletar -> 403
    res_del = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/attachments/slides.pdf",
        headers=tenant.admin.auth_headers,
    )
    assert res_del.status_code == 403
