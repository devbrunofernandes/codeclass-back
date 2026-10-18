import io
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.exceptions import StorageError
from app.infrastructure.storage.base import StorageProvider
from app.services.storage_service import (
    CLASSROOM_MATERIALS_BUCKET,
    StorageService,
)

pytestmark = pytest.mark.usefixtures("mocked_blocking_io")


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


async def test_upload_profile_photo_when_valid_should_use_single_tenant_path(
    storage_service, mock_storage_provider, profile_photo_bytes
):
    org, user = uuid.uuid4(), uuid.uuid4()
    for name in ("a.png", "b.png"):
        path = await storage_service.upload_profile_photo(
            org,
            user,
            UploadFile(
                io.BytesIO(profile_photo_bytes),
                filename=name,
                headers=Headers({"content-type": "image/png"}),
            ),
        )
        assert path == f"{org}/{user}/profile.jpg"
    assert mock_storage_provider.upload_file.await_count == 2
    assert mock_storage_provider.upload_file.call_args.kwargs["bucket"] == "user-photos"


@pytest.mark.parametrize(
    "content,mime,status",
    [
        (b"", "image/png", 400),
        (b"fake", "image/png", 400),
        (b"<svg/>", "image/svg+xml", 400),
        (b"x" * (5 * 1024 * 1024 + 1), "image/png", 413),
    ],
    ids=["empty", "corrupt", "svg", "oversized"],
)
async def test_upload_profile_photo_when_invalid_should_reject_before_storage(
    storage_service, mock_storage_provider, content, mime, status
):
    with pytest.raises(StorageError) as error:
        await storage_service.upload_profile_photo(
            uuid.uuid4(),
            uuid.uuid4(),
            UploadFile(
                io.BytesIO(content),
                filename="photo",
                headers=Headers({"content-type": mime}),
            ),
        )
    assert error.value.status_code == status
    mock_storage_provider.upload_file.assert_not_awaited()


async def test_profile_photo_urls_when_multiple_users_should_sign_once(
    storage_service, mock_storage_provider
):
    org, first, second, empty = (uuid.uuid4() for _ in range(4))
    paths = {
        first: f"{org}/{first}/profile.jpg",
        second: f"{org}/{second}/profile.jpg",
        empty: None,
    }
    result = await storage_service.get_profile_photo_fields(org, paths)
    assert result[first].profile_photo_url == "https://storage.example.com/signed"
    assert result[second].profile_photo_url_expires_at is not None
    assert result[empty].profile_photo_url is None
    assert all(
        set(photo.model_dump()) == {"profile_photo_url", "profile_photo_url_expires_at"}
        for photo in result.values()
    )
    mock_storage_provider.get_signed_urls.assert_awaited_once_with(
        bucket="user-photos", paths=[paths[first], paths[second]], expires_in=3600
    )


async def test_profile_photo_urls_when_empty_or_foreign_should_not_sign(
    storage_service, mock_storage_provider
):
    org, user = uuid.uuid4(), uuid.uuid4()
    for path in (None, f"{uuid.uuid4()}/{user}/profile.jpg"):
        result = await storage_service.get_profile_photo_fields(org, {user: path})
        assert result[user].profile_photo_url is None
    mock_storage_provider.get_signed_urls.assert_not_awaited()


async def test_profile_photo_urls_when_provider_fails_should_preserve_profile(
    storage_service, mock_storage_provider
):
    org, user = uuid.uuid4(), uuid.uuid4()
    mock_storage_provider.get_signed_urls.side_effect = StorageError("Unavailable", 502)
    result = await storage_service.get_profile_photo_fields(
        org, {user: f"{org}/{user}/profile.jpg"}
    )
    assert result[user].profile_photo_url is None
