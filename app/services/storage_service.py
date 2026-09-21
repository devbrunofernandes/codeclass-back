import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import StorageError
from supabase import Client, ClientOptions, create_client

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB conforme HLD (RF23)
CLASSROOM_MATERIALS_BUCKET = "classroom-materials"


class StorageService:
    def __init__(self) -> None:
        self._client: Client | None = None

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

    async def upload_classroom_material(
        self,
        organization_id: UUID,
        classroom_id: UUID,
        file: UploadFile,
    ) -> dict[str, Any]:
        """Faz upload de material didático em streaming com validação de 30MB (RNF/HLD 9.3)."""
        raw_name = Path(file.filename or "unnamed_file").name
        safe_file_name = raw_name.replace("/", "_").replace("\\", "_")
        if not safe_file_name or safe_file_name in (".", ".."):
            safe_file_name = "unnamed_file"
        storage_path = f"{organization_id}/{classroom_id}/{safe_file_name}"

        # Lê em chunks para validar tamanho máximo sem estourar memória (HLD 9.3)
        chunk_size = 1024 * 1024  # 1MB por chunk
        total_size = 0
        chunks: list[bytes] = []

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > MAX_FILE_SIZE:
                raise StorageError(
                    "Tamanho do arquivo excede o limite máximo permitido de 30MB.",
                    status_code=413,
                )
            chunks.append(chunk)

        file_bytes = b"".join(chunks)
        content_type = file.content_type or "application/octet-stream"

        try:
            client = self._get_client()
            await anyio.to_thread.run_sync(
                lambda: client.storage.from_(CLASSROOM_MATERIALS_BUCKET).upload(
                    path=storage_path,
                    file=file_bytes,
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

        return {
            "file_name": safe_file_name,
            "file_path": storage_path,
            "size_bytes": total_size,
            "content_type": content_type,
        }

    async def create_signed_download_url(
        self,
        organization_id: UUID,
        classroom_id: UUID,
        file_name: str,
        expires_in: int = 3600,
    ) -> str:
        """Gera URL assinada temporária para download seguro diretamente do storage (HLD 9.3)."""
        safe_file_name = file_name.replace("/", "_").replace("\\", "_")
        storage_path = f"{organization_id}/{classroom_id}/{safe_file_name}"

        try:
            client = self._get_client()
            res = await anyio.to_thread.run_sync(
                lambda: client.storage.from_(
                    CLASSROOM_MATERIALS_BUCKET
                ).create_signed_url(
                    path=storage_path,
                    expires_in=expires_in,
                )
            )
            # res pode ser um dict ou objeto com 'signedURL' ou 'signed_url'
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

    async def list_classroom_materials(
        self,
        organization_id: UUID,
        classroom_id: UUID,
    ) -> list[dict[str, Any]]:
        """Lista metadados dos arquivos anexados à sala no storage."""
        folder_prefix = f"{organization_id}/{classroom_id}"

        try:
            client = self._get_client()
            files = await anyio.to_thread.run_sync(
                lambda: client.storage.from_(CLASSROOM_MATERIALS_BUCKET).list(
                    path=folder_prefix
                )
            )
            results: list[dict[str, Any]] = []
            for item in files:
                name = item.get("name")
                if not name or name == ".emptyFolderPlaceholder":
                    continue
                metadata = item.get("metadata") or {}
                results.append(
                    {
                        "file_name": name,
                        "file_path": f"{folder_prefix}/{name}",
                        "size_bytes": metadata.get("size", 0),
                        "content_type": metadata.get("mimetype"),
                        "uploaded_at": item.get("created_at"),
                    }
                )
            return results
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao listar arquivos do Supabase Storage: %s", e)
            return []

    async def delete_classroom_material(
        self,
        organization_id: UUID,
        classroom_id: UUID,
        file_name: str,
    ) -> None:
        """Exclui arquivo do storage."""
        safe_file_name = file_name.replace("/", "_").replace("\\", "_")
        storage_path = f"{organization_id}/{classroom_id}/{safe_file_name}"

        try:
            client = self._get_client()
            await anyio.to_thread.run_sync(
                lambda: client.storage.from_(CLASSROOM_MATERIALS_BUCKET).remove(
                    [storage_path]
                )
            )
        except Exception as e:
            if isinstance(e, StorageError):
                raise
            logger.error("Erro ao excluir arquivo do Supabase Storage: %s", e)
            raise StorageError(
                f"Falha ao excluir arquivo: {e!s}", status_code=500
            ) from e


storage_service = StorageService()
