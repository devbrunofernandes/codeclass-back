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


def test_get_client_missing_config_raises_500(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")

    with pytest.raises(
        StorageError, match="Configurações do provedor de armazenamento ausentes."
    ) as exc_info:
        storage_service._get_client()
    assert exc_info.value.status_code == 500


def test_get_client_success_creates_and_caches_client(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "example-key")
    mock_create = MagicMock()
    monkeypatch.setattr("app.services.storage_service.create_client", mock_create)

    client1 = storage_service._get_client()
    client2 = storage_service._get_client()

    assert client1 is mock_create.return_value
    assert client2 is client1
    mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_upload_classroom_material_dot_filename_sanitized_to_unnamed_file(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(return_value={"Key": "unnamed_file"})
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    file = UploadFile(filename="..", file=io.BytesIO(b"data"))
    res = await storage_service.upload_classroom_material(
        organization_id=uuid.uuid4(),
        classroom_id=uuid.uuid4(),
        file=file,
    )
    assert res["file_name"] == "unnamed_file"


@pytest.mark.asyncio
async def test_upload_classroom_material_re_raises_existing_storage_error(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(side_effect=StorageError("Custom upload error", 400))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    file = UploadFile(filename="test.pdf", file=io.BytesIO(b"data"))
    with pytest.raises(StorageError) as exc_info:
        await storage_service.upload_classroom_material(
            organization_id=uuid.uuid4(),
            classroom_id=uuid.uuid4(),
            file=file,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_create_signed_download_url_variations(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    org_id = uuid.uuid4()
    cls_id = uuid.uuid4()

    # Variação 1: objeto com hasattr 'signed_url'
    class ObjSignedUrl:
        signed_url = "https://example.com/has_signed_url"

    mock_bucket.create_signed_url.return_value = ObjSignedUrl()
    url1 = await storage_service.create_signed_download_url(org_id, cls_id, "f1.pdf")
    assert url1 == "https://example.com/has_signed_url"

    # Variação 2: objeto com hasattr 'signedURL'
    class ObjSignedURLUpper:
        signedURL = "https://example.com/has_signedURL"

    mock_bucket.create_signed_url.return_value = ObjSignedURLUpper()
    url2 = await storage_service.create_signed_download_url(org_id, cls_id, "f2.pdf")
    assert url2 == "https://example.com/has_signedURL"

    # Variação 3: dict com 'signed_url' em snake_case
    mock_bucket.create_signed_url.return_value = {
        "signed_url": "https://example.com/dict_snake"
    }
    url3 = await storage_service.create_signed_download_url(org_id, cls_id, "f3.pdf")
    assert url3 == "https://example.com/dict_snake"

    # Variação 4: retorno vazio/sem url assinada -> StorageError 500
    mock_bucket.create_signed_url.return_value = {}
    with pytest.raises(StorageError) as exc_info:
        await storage_service.create_signed_download_url(org_id, cls_id, "f4.pdf")
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_list_classroom_materials_exception_returns_empty_list(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list = MagicMock(side_effect=RuntimeError("Storage connection failed"))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    res = await storage_service.list_classroom_materials(uuid.uuid4(), uuid.uuid4())
    assert res == []


@pytest.mark.asyncio
async def test_list_classroom_materials_storage_error_re_raised(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list = MagicMock(side_effect=StorageError("Forbidden bucket", 403))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    with pytest.raises(StorageError) as exc_info:
        await storage_service.list_classroom_materials(uuid.uuid4(), uuid.uuid4())
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_delete_classroom_material_re_raises_existing_storage_error(
    storage_service: StorageService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_supabase = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.remove = MagicMock(side_effect=StorageError("Not allowed", 403))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_supabase.storage = mock_storage
    monkeypatch.setattr(storage_service, "_get_client", lambda: mock_supabase)

    with pytest.raises(StorageError) as exc_info:
        await storage_service.delete_classroom_material(
            organization_id=uuid.uuid4(),
            classroom_id=uuid.uuid4(),
            file_name="aula1.pdf",
        )
    assert exc_info.value.status_code == 403
