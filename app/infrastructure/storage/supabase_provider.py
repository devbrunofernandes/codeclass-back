import io
import logging
import tempfile
from typing import IO, Any, BinaryIO

import anyio

from app.core.config import settings
from app.core.exceptions import StorageError
from app.infrastructure.storage.base import StorageProvider
from supabase import Client, ClientOptions, create_client

logger = logging.getLogger(__name__)


def _prepare_upload_file(file: IO[bytes] | BinaryIO | bytes) -> Any:
    """Prepara o arquivo ou stream para upload no Supabase Storage sem carregar 30MB em memória.

    Retorna o payload compatível com storage3 (bytes, BufferedReader, FileIO).
    """
    if isinstance(file, (bytes, io.BufferedReader, io.FileIO)):
        return file

    if isinstance(file, io.BytesIO):
        return file.getvalue()

    if isinstance(file, tempfile.SpooledTemporaryFile) or hasattr(file, "_file"):
        underlying = getattr(file, "_file", None)
        if underlying is not None:
            if isinstance(underlying, io.BytesIO):
                return underlying.getvalue()
            raw = getattr(underlying, "raw", None)
            if isinstance(raw, io.FileIO):
                return raw
            if isinstance(underlying, (io.BufferedReader, io.FileIO)):
                return underlying

    return file


class SupabaseStorageProvider(StorageProvider):
    """Implementação do provedor de armazenamento utilizando o Supabase Storage SDK."""

    def __init__(self, client: Client | None = None) -> None:
        self._client: Client | None = client

    def _get_client(self) -> Client:
        if self._client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
                raise StorageError(
                    "Configurações do provedor de armazenamento ausentes.",
                    status_code=500,
                )
            self._client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_KEY,
                options=ClientOptions(
                    persist_session=False,
                    auto_refresh_token=False,
                ),
            )
        return self._client

    async def _execute_upload(
        self,
        bucket: str,
        path: str,
        prepared_file: Any,
        content_type: str,
    ) -> None:
        try:
            client = self._get_client()
            await anyio.to_thread.run_sync(
                lambda: client.storage.from_(bucket).upload(
                    path=path,
                    file=prepared_file,
                    file_options={"content-type": content_type, "upsert": "true"},
                )
            )
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao realizar upload no Supabase Storage: %s", e)
            raise StorageError(
                f"Falha no upload do arquivo: {e!s}", status_code=500
            ) from e

    async def upload_file(
        self,
        bucket: str,
        path: str,
        file: IO[bytes] | BinaryIO,
        content_type: str,
    ) -> None:
        """Faz upload de arquivo com streaming seguro via SpooledTemporaryFile."""
        if not isinstance(
            file, (bytes, io.BufferedReader, io.FileIO, io.BytesIO)
        ) and not hasattr(file, "_file"):
            with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as spooled:
                while True:
                    chunk = file.read(1024 * 1024)
                    if not chunk:
                        break
                    spooled.write(chunk)
                spooled.seek(0)
                await self._execute_upload(
                    bucket=bucket,
                    path=path,
                    prepared_file=_prepare_upload_file(spooled),
                    content_type=content_type,
                )
                return

        prepared_file = _prepare_upload_file(file)
        await self._execute_upload(
            bucket=bucket,
            path=path,
            prepared_file=prepared_file,
            content_type=content_type,
        )

    async def list_files(
        self,
        bucket: str,
        prefix: str,
    ) -> list[dict[str, Any]]:
        """Lista os arquivos no bucket sob o prefixo informado."""
        try:
            client = self._get_client()
            files = await anyio.to_thread.run_sync(
                lambda: client.storage.from_(bucket).list(path=prefix)
            )
            return files or []
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao listar arquivos do Supabase Storage: %s", e)
            return []

    async def delete_file(
        self,
        bucket: str,
        path: str,
    ) -> None:
        """Exclui o arquivo no caminho informado dentro do bucket."""
        try:
            client = self._get_client()
            await anyio.to_thread.run_sync(
                lambda: client.storage.from_(bucket).remove([path])
            )
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao excluir arquivo do Supabase Storage: %s", e)
            raise StorageError(
                f"Falha ao excluir arquivo: {e!s}", status_code=500
            ) from e

    async def get_signed_url(
        self,
        bucket: str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """Gera Signed URL temporária no Supabase Storage para download seguro."""
        try:
            client = self._get_client()
            res = await anyio.to_thread.run_sync(
                lambda: client.storage.from_(bucket).create_signed_url(
                    path=path,
                    expires_in=expires_in,
                )
            )
            signed_url: str | None = None
            if isinstance(res, dict):
                raw_url = res.get("signedURL") or res.get("signed_url")
                signed_url = str(raw_url) if raw_url else None
            elif hasattr(res, "signed_url"):
                signed_url = str(res.signed_url)
            elif hasattr(res, "signedURL"):
                signed_url = str(res.signedURL)

            if not signed_url:
                raise StorageError(
                    "URL assinada não retornada pelo storage.", status_code=500
                )
            return signed_url
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao gerar signed URL no Supabase Storage: %s", e)
            raise StorageError(
                "Arquivo não encontrado ou erro ao gerar URL de download.",
                status_code=404,
            ) from e
