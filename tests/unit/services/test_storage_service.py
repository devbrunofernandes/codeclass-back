import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.core.exceptions import StorageError
from app.infrastructure.storage.base import StorageProvider
from app.services.storage_service import (
    CLASSROOM_MATERIALS_BUCKET,
    StorageService,
)


@pytest.fixture
def mock_storage_provider() -> MagicMock:
    provider = MagicMock(spec=StorageProvider)
    provider.upload_file = AsyncMock()
    provider.get_signed_url = AsyncMock(
        return_value="https://storage.example.com/signed"
    )
    provider.list_files = AsyncMock(return_value=[])
    provider.delete_file = AsyncMock()
    return provider


@pytest.fixture
def storage_service(mock_storage_provider: MagicMock) -> StorageService:
    return StorageService(provider=mock_storage_provider)


def test_storage_service_default_provider(monkeypatch: pytest.MonkeyPatch):
    mock_default = MagicMock(spec=StorageProvider)
    monkeypatch.setattr(
        "app.services.storage_service.get_storage_provider", lambda: mock_default
    )
    service = StorageService()
    assert service.provider is mock_default


@pytest.mark.asyncio
async def test_upload_classroom_material_success(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    content = b"Conteudo do arquivo de teste"
    file = UploadFile(
        filename="test.pdf",
        file=io.BytesIO(content),
        headers={"content-type": "application/pdf"},
    )
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
    assert result["content_type"] == "application/pdf"

    mock_storage_provider.upload_file.assert_awaited_once()
    call_kwargs = mock_storage_provider.upload_file.call_args[1]
    assert call_kwargs["bucket"] == CLASSROOM_MATERIALS_BUCKET
    assert call_kwargs["path"] == f"{org_id}/{cls_id}/test.pdf"
    assert call_kwargs["content_type"] == "application/pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected_name"),
    [
        ("aula/slides.pdf", "slides.pdf"),
        ("aula\\slides.pdf", "aula_slides.pdf"),
        (".", "unnamed_file"),
        ("..", "unnamed_file"),
        (None, "unnamed_file"),
    ],
)
async def test_upload_classroom_material_filename_sanitization(
    storage_service: StorageService,
    mock_storage_provider: MagicMock,
    filename: str | None,
    expected_name: str,
):
    file = UploadFile(
        filename=filename,  # type: ignore
        file=io.BytesIO(b"data"),
    )
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    result = await storage_service.upload_classroom_material(
        organization_id=org_id,
        classroom_id=cls_id,
        file=file,
    )

    assert result["file_name"] == expected_name
    assert result["file_path"] == f"{org_id}/{cls_id}/{expected_name}"


@pytest.mark.asyncio
async def test_upload_classroom_material_exceeds_30mb(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    class LargeUploadFile:
        filename = "huge.bin"
        content_type = "application/octet-stream"

        def __init__(self) -> None:
            # 2 chunks de 16MB = 32MB > 30MB
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
    mock_storage_provider.upload_file.assert_not_called()


@pytest.mark.asyncio
async def test_upload_classroom_material_re_raises_provider_error(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    mock_storage_provider.upload_file.side_effect = StorageError("Upload failed", 500)
    file = UploadFile(filename="test.pdf", file=io.BytesIO(b"content"))

    with pytest.raises(StorageError) as exc_info:
        await storage_service.upload_classroom_material(
            organization_id=uuid.uuid4(),
            classroom_id=uuid.uuid4(),
            file=file,
        )
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_create_signed_download_url(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    url = await storage_service.create_signed_download_url(
        organization_id=org_id,
        classroom_id=cls_id,
        file_name="sub/slide.pdf",
        expires_in=7200,
    )

    assert url == "https://storage.example.com/signed"
    mock_storage_provider.get_signed_url.assert_awaited_once_with(
        bucket=CLASSROOM_MATERIALS_BUCKET,
        path=f"{org_id}/{cls_id}/sub_slide.pdf",
        expires_in=7200,
    )


@pytest.mark.asyncio
async def test_list_classroom_materials(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()
    folder_prefix = f"{org_id}/{cls_id}"

    mock_storage_provider.list_files.return_value = [
        {
            "name": "aula1.pdf",
            "created_at": "2026-09-20T20:00:00Z",
            "metadata": {"size": 2048, "mimetype": "application/pdf"},
        },
        {"name": ".emptyFolderPlaceholder"},
        {"name": ""},
    ]

    materials = await storage_service.list_classroom_materials(
        organization_id=org_id,
        classroom_id=cls_id,
    )

    assert len(materials) == 1
    assert materials[0]["file_name"] == "aula1.pdf"
    assert materials[0]["file_path"] == f"{folder_prefix}/aula1.pdf"
    assert materials[0]["size_bytes"] == 2048
    assert materials[0]["content_type"] == "application/pdf"
    assert materials[0]["uploaded_at"] == "2026-09-20T20:00:00Z"

    mock_storage_provider.list_files.assert_awaited_once_with(
        bucket=CLASSROOM_MATERIALS_BUCKET,
        prefix=folder_prefix,
    )


@pytest.mark.asyncio
async def test_delete_classroom_material(
    storage_service: StorageService, mock_storage_provider: MagicMock
):
    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    await storage_service.delete_classroom_material(
        organization_id=org_id,
        classroom_id=cls_id,
        file_name="sub/aula1.pdf",
    )

    mock_storage_provider.delete_file.assert_awaited_once_with(
        bucket=CLASSROOM_MATERIALS_BUCKET,
        path=f"{org_id}/{cls_id}/sub_aula1.pdf",
    )
