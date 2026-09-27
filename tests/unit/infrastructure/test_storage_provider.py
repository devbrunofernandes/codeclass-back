import io
import tempfile
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import StorageError
from app.infrastructure.storage.factory import get_storage_provider
from app.infrastructure.storage.supabase_provider import (
    SupabaseStorageProvider,
    _prepare_upload_file,
)


def test_get_storage_provider_default():
    provider = get_storage_provider()
    assert isinstance(provider, SupabaseStorageProvider)


def test_get_storage_provider_unsupported(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "unsupported_storage")
    with pytest.raises(ValueError, match="Provedor de storage não suportado"):
        get_storage_provider()


def test_supabase_provider_get_client_missing_config_raises_500(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")

    provider = SupabaseStorageProvider()
    with pytest.raises(
        StorageError, match="Configurações do provedor de armazenamento ausentes."
    ) as exc_info:
        provider._get_client()
    assert exc_info.value.status_code == 500


def test_supabase_provider_get_client_success_creates_and_caches_client(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "example-key")
    mock_create = MagicMock()
    monkeypatch.setattr(
        "app.infrastructure.storage.supabase_provider.create_client", mock_create
    )

    provider = SupabaseStorageProvider()
    client1 = provider._get_client()
    client2 = provider._get_client()

    assert client1 is mock_create.return_value
    assert client2 is client1
    mock_create.assert_called_once()


def test_prepare_upload_file_types():
    # 1. bytes direto
    data = b"raw bytes"
    assert _prepare_upload_file(data) == data

    # 2. BytesIO -> extrai bytes
    bio = io.BytesIO(b"bio bytes")
    assert _prepare_upload_file(bio) == b"bio bytes"

    # 3. SpooledTemporaryFile em memória (< max_size) -> extrai bytes
    with tempfile.SpooledTemporaryFile(max_size=1024) as s_mem:
        s_mem.write(b"spooled in mem")
        s_mem.seek(0)
        prepared_mem = _prepare_upload_file(s_mem)
        assert prepared_mem == b"spooled in mem"

    # 4. SpooledTemporaryFile que estourou para disco (> max_size) -> retorna raw FileIO
    with tempfile.SpooledTemporaryFile(max_size=10) as s_disk:
        s_disk.write(b"x" * 50)
        s_disk.seek(0)
        prepared_disk = _prepare_upload_file(s_disk)
        assert isinstance(prepared_disk, (io.FileIO, io.BufferedReader))

    # 5. Objeto com _file que é BufferedReader direto (sem .raw)
    class DummyWrapper:
        def __init__(self, stream: io.BufferedReader) -> None:
            self._file = stream

    reader = io.BufferedReader(io.BytesIO(b"data"))  # type: ignore[arg-type]
    wrapper = DummyWrapper(reader)
    assert _prepare_upload_file(wrapper) is reader  # type: ignore[arg-type]

    # 6. Fallback objeto desconhecido sem _file
    unknown = object()
    assert _prepare_upload_file(unknown) is unknown  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_supabase_provider_upload_file_custom_stream():
    class CustomStream:
        def __init__(self, content: bytes) -> None:
            self._bio = io.BytesIO(content)

        def read(self, size: int = -1) -> bytes:
            return self._bio.read(size)

    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(return_value={"Key": "test.pdf"})
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)
    cs = CustomStream(b"custom stream data")

    await provider.upload_file(
        bucket="test-bucket",
        path="folder/test.pdf",
        file=cs,  # type: ignore[arg-type]
        content_type="application/octet-stream",
    )
    mock_bucket.upload.assert_called_once()


@pytest.mark.asyncio
async def test_supabase_provider_upload_file_success(monkeypatch: pytest.MonkeyPatch):
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(return_value={"Key": "test.pdf"})
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)

    file_obj = io.BytesIO(b"content")
    await provider.upload_file(
        bucket="test-bucket",
        path="folder/test.pdf",
        file=file_obj,
        content_type="application/pdf",
    )

    mock_storage.from_.assert_called_once_with("test-bucket")
    mock_bucket.upload.assert_called_once()
    call_kwargs = mock_bucket.upload.call_args[1]
    assert call_kwargs["path"] == "folder/test.pdf"
    assert call_kwargs["file_options"] == {
        "content-type": "application/pdf",
        "upsert": "true",
    }


@pytest.mark.asyncio
async def test_supabase_provider_upload_file_re_raises_storage_error():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(
        side_effect=StorageError("Custom storage error", 400)
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)
    with pytest.raises(StorageError) as exc_info:
        await provider.upload_file(
            bucket="test-bucket",
            path="file.pdf",
            file=io.BytesIO(b"data"),
            content_type="application/pdf",
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_supabase_provider_upload_file_generic_exception():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.upload = MagicMock(side_effect=Exception("Connection reset"))
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)
    with pytest.raises(StorageError) as exc_info:
        await provider.upload_file(
            bucket="test-bucket",
            path="file.pdf",
            file=io.BytesIO(b"data"),
            content_type="application/pdf",
        )
    assert exc_info.value.status_code == 500
    assert "Falha no upload do arquivo" in exc_info.value.message


@pytest.mark.asyncio
async def test_supabase_provider_get_signed_url_success():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.create_signed_url = MagicMock(
        return_value={"signedURL": "https://storage.supabase.co/signed?token=abc"}
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)
    url = await provider.get_signed_url(
        bucket="test-bucket", path="folder/file.pdf", expires_in=1800
    )

    assert url == "https://storage.supabase.co/signed?token=abc"
    mock_bucket.create_signed_url.assert_called_once_with(
        path="folder/file.pdf", expires_in=1800
    )


@pytest.mark.asyncio
async def test_supabase_provider_get_signed_url_variations():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)

    # 1. Objeto com hasattr 'signed_url'
    class ObjSignedUrl:
        signed_url = "https://example.com/has_signed_url"

    mock_bucket.create_signed_url.return_value = ObjSignedUrl()
    url1 = await provider.get_signed_url("b", "p1")
    assert url1 == "https://example.com/has_signed_url"

    # 2. Objeto com hasattr 'signedURL'
    class ObjSignedURLUpper:
        signedURL = "https://example.com/has_signedURL"

    mock_bucket.create_signed_url.return_value = ObjSignedURLUpper()
    url2 = await provider.get_signed_url("b", "p2")
    assert url2 == "https://example.com/has_signedURL"

    # 3. Dict com snake_case
    mock_bucket.create_signed_url.return_value = {
        "signed_url": "https://example.com/dict_snake"
    }
    url3 = await provider.get_signed_url("b", "p3")
    assert url3 == "https://example.com/dict_snake"

    # 4. Retorno sem url -> StorageError 500
    mock_bucket.create_signed_url.return_value = {}
    with pytest.raises(StorageError) as exc_info:
        await provider.get_signed_url("b", "p4")
    assert exc_info.value.status_code == 500

    # 5. StorageError lançado diretamente
    mock_bucket.create_signed_url.side_effect = StorageError("Direct error", 403)
    with pytest.raises(StorageError) as exc_info_direct:
        await provider.get_signed_url("b", "p5")
    assert exc_info_direct.value.status_code == 403

    # 6. Exceção genérica -> 404
    mock_bucket.create_signed_url.side_effect = Exception("Not found")
    with pytest.raises(StorageError) as exc_info_404:
        await provider.get_signed_url("b", "p6")
    assert exc_info_404.value.status_code == 404


@pytest.mark.asyncio
async def test_supabase_provider_list_files_success():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.list = MagicMock(
        return_value=[
            {"name": "file1.pdf", "metadata": {"size": 100}},
            {"name": "file2.pdf", "metadata": {"size": 200}},
        ]
    )
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)
    res = await provider.list_files("bucket", "prefix")

    assert len(res) == 2
    mock_bucket.list.assert_called_once_with(path="prefix")


@pytest.mark.asyncio
async def test_supabase_provider_list_files_errors():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)

    # 1. StorageError é repassada
    mock_bucket.list.side_effect = StorageError("Bucket error", 403)
    with pytest.raises(StorageError) as exc_info:
        await provider.list_files("b", "p")
    assert exc_info.value.status_code == 403

    # 2. Exceção genérica -> retorna lista vazia
    mock_bucket.list.side_effect = RuntimeError("Network glitch")
    res = await provider.list_files("b", "p")
    assert res == []


@pytest.mark.asyncio
async def test_supabase_provider_delete_file_success_and_errors():
    mock_client = MagicMock()
    mock_storage = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.remove = MagicMock(return_value=None)
    mock_storage.from_ = MagicMock(return_value=mock_bucket)
    mock_client.storage = mock_storage

    provider = SupabaseStorageProvider(client=mock_client)

    # 1. Sucesso
    await provider.delete_file("bucket", "path/to/file.pdf")
    mock_bucket.remove.assert_called_once_with(["path/to/file.pdf"])

    # 2. StorageError repassada
    mock_bucket.remove.side_effect = StorageError("Not permitted", 403)
    with pytest.raises(StorageError) as exc_info:
        await provider.delete_file("bucket", "path/to/file.pdf")
    assert exc_info.value.status_code == 403

    # 3. Exceção genérica -> 500
    mock_bucket.remove.side_effect = Exception("Storage timeout")
    with pytest.raises(StorageError) as exc_info_500:
        await provider.delete_file("bucket", "path/to/file.pdf")
    assert exc_info_500.value.status_code == 500
