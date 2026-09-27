import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import UploadFile

from app.core.exceptions import StorageError
from app.infrastructure.storage.base import StorageProvider
from app.infrastructure.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB
CLASSROOM_MATERIALS_BUCKET = "classroom-materials"


class StorageService:
    """Serviço de aplicação para gestão de arquivos e materiais didáticos.

    Totalmente desacoplado do provedor subjacente via inversão de controle (Strategy Pattern).
    """

    def __init__(self, provider: StorageProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> StorageProvider:
        if self._provider is None:
            self._provider = get_storage_provider()
        return self._provider

    async def upload_classroom_material(
        self,
        organization_id: UUID,
        classroom_id: UUID,
        file: UploadFile,
    ) -> dict[str, Any]:
        """Faz upload de material didático em streaming com validação de limite de 30MB."""
        raw_name = Path(file.filename or "unnamed_file").name
        safe_file_name = raw_name.replace("/", "_").replace("\\", "_")
        if not safe_file_name or safe_file_name in (".", ".."):
            safe_file_name = "unnamed_file"
        storage_path = f"{organization_id}/{classroom_id}/{safe_file_name}"

        chunk_size = 1024 * 1024  # 1MB por chunk
        total_size = 0

        # Utiliza SpooledTemporaryFile para evitar alocação de 30MB na memória RAM
        with tempfile.SpooledTemporaryFile(max_size=chunk_size) as spooled:
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
                spooled.write(chunk)

            spooled.seek(0)
            content_type = file.content_type or "application/octet-stream"

            await self.provider.upload_file(
                bucket=CLASSROOM_MATERIALS_BUCKET,
                path=storage_path,
                file=spooled,
                content_type=content_type,
            )

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

        return await self.provider.get_signed_url(
            bucket=CLASSROOM_MATERIALS_BUCKET,
            path=storage_path,
            expires_in=expires_in,
        )

    async def list_classroom_materials(
        self,
        organization_id: UUID,
        classroom_id: UUID,
    ) -> list[dict[str, Any]]:
        """Lista metadados dos arquivos anexados à sala no storage."""
        folder_prefix = f"{organization_id}/{classroom_id}"

        files = await self.provider.list_files(
            bucket=CLASSROOM_MATERIALS_BUCKET,
            prefix=folder_prefix,
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

    async def delete_classroom_material(
        self,
        organization_id: UUID,
        classroom_id: UUID,
        file_name: str,
    ) -> None:
        """Exclui arquivo do storage."""
        safe_file_name = file_name.replace("/", "_").replace("\\", "_")
        storage_path = f"{organization_id}/{classroom_id}/{safe_file_name}"

        await self.provider.delete_file(
            bucket=CLASSROOM_MATERIALS_BUCKET,
            path=storage_path,
        )


storage_service = StorageService()

__all__ = [
    "CLASSROOM_MATERIALS_BUCKET",
    "MAX_FILE_SIZE",
    "StorageError",
    "StorageService",
    "storage_service",
]
