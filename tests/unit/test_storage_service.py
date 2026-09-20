import io
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

from app.services.storage_service import StorageError, StorageService


@pytest.fixture
def storage_service() -> StorageService:
    return StorageService()


@pytest.mark.asyncio
async def test_upload_classroom_material_success(
    storage_service: StorageService, monkeypatch
):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(return_value={"Key": "test.pdf"})
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    content = b"Conteudo do arquivo de teste em bytes"
    file = UploadFile(filename="test.pdf", file=io.BytesIO(content))
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    result = await storage_service.upload_classroom_material(
        organization_id=org_id,
        classroom_id=cls_id,
        file=file,
    )

    assert result["file_name"] == "test.pdf"
    assert result["file_path"] == f"{org_id}/{cls_id}/test.pdf"
    assert result["size_bytes"] == len(content)
    mock_bucket.upload.assert_called_once()


@pytest.mark.asyncio
async def test_upload_classroom_material_exceeds_30mb(
    storage_service: StorageService, monkeypatch
):
    class LargeUploadFile:
        filename = "huge.bin"
        content_type = "application/octet-stream"

        def __init__(self) -> None:
            # Chunks de 16MB x 2 -> 32MB > 30MB
            self.chunk = b"x" * (16 * 1024 * 1024)
            self.count = 0

        async def read(self, size: int = -1) -> bytes:
            if self.count < 2:
                self.count += 1
                return self.chunk
            return b""

    large_file = LargeUploadFile()
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    with pytest.raises(StorageError) as exc_info:
        await storage_service.upload_classroom_material(
            organization_id=org_id,
            classroom_id=cls_id,
            file=large_file,  # type: ignore
        )

    assert exc_info.value.status_code == 413
    assert "30MB" in exc_info.value.message


@pytest.mark.asyncio
async def test_upload_classroom_material_supabase_error(
    storage_service: StorageService, monkeypatch
):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(side_effect=Exception("Storage network error"))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    file = UploadFile(filename="doc.pdf", file=io.BytesIO(b"data"))

    with pytest.raises(StorageError) as exc_info:
        await storage_service.upload_classroom_material(
            organization_id=uuid.uuid4(),
            classroom_id=uuid.uuid4(),
            file=file,
        )

    assert exc_info.value.status_code == 500
    assert "Falha no upload do arquivo" in exc_info.value.message


@pytest.mark.asyncio
async def test_create_signed_download_url_success_dict(
    storage_service: StorageService, monkeypatch
):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.create_signed_url = MagicMock(
        return_value={"signedURL": "https://storage.supabase.co/signed?token=abc"}
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    url = await storage_service.create_signed_download_url(
        organization_id=org_id,
        classroom_id=cls_id,
        file_name="slide.pdf",
        expires_in=3600,
    )

    assert url == "https://storage.supabase.co/signed?token=abc"
    mock_bucket.create_signed_url.assert_called_once_with(
        path=f"{org_id}/{cls_id}/slide.pdf",
        expires_in=3600,
    )


@pytest.mark.asyncio
async def test_create_signed_download_url_failure(
    storage_service: StorageService, monkeypatch
):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.create_signed_url = MagicMock(
        side_effect=Exception("Supabase token failure")
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    with pytest.raises(StorageError) as exc_info:
        await storage_service.create_signed_download_url(
            organization_id=uuid.uuid4(),
            classroom_id=uuid.uuid4(),
            file_name="slide.pdf",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_classroom_materials(storage_service: StorageService, monkeypatch):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list = MagicMock(
        return_value=[
            {
                "name": "aula1.pdf",
                "created_at": "2026-09-20T20:00:00Z",
                "metadata": {"size": 2048, "mimetype": "application/pdf"},
            },
            {"name": ".emptyFolderPlaceholder"},
        ]
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()
    materials = await storage_service.list_classroom_materials(
        organization_id=org_id, classroom_id=cls_id
    )

    assert len(materials) == 1
    assert materials[0]["file_name"] == "aula1.pdf"
    assert materials[0]["size_bytes"] == 2048


@pytest.mark.asyncio
async def test_delete_classroom_material_success_and_error(
    storage_service: StorageService, monkeypatch
):
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.remove = MagicMock(return_value=None)
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    # Sucesso
    await storage_service.delete_classroom_material(
        organization_id=org_id,
        classroom_id=cls_id,
        file_name="aula1.pdf",
    )
    mock_bucket.remove.assert_called_once_with([f"{org_id}/{cls_id}/aula1.pdf"])

    # Falha
    mock_bucket.remove.side_effect = Exception("Storage error")
    with pytest.raises(StorageError) as exc_info:
        await storage_service.delete_classroom_material(
            organization_id=org_id,
            classroom_id=cls_id,
            file_name="aula1.pdf",
        )
    assert exc_info.value.status_code == 500
