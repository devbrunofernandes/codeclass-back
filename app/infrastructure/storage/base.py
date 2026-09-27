from abc import ABC, abstractmethod
from typing import IO, Any, BinaryIO


class StorageProvider(ABC):
    """Interface abstrata (Strategy Pattern) para provedores de armazenamento de arquivos."""

    @abstractmethod
    async def upload_file(
        self,
        bucket: str,
        path: str,
        file: IO[bytes] | BinaryIO,
        content_type: str,
    ) -> None:
        """Faz upload de arquivo para o bucket e caminho especificados."""

    @abstractmethod
    async def list_files(
        self,
        bucket: str,
        prefix: str,
    ) -> list[dict[str, Any]]:
        """Lista arquivos no bucket sob o prefixo informado."""

    @abstractmethod
    async def delete_file(
        self,
        bucket: str,
        path: str,
    ) -> None:
        """Exclui o arquivo no caminho especificado."""

    @abstractmethod
    async def get_signed_url(
        self,
        bucket: str,
        path: str,
        expires_in: int = 3600,
    ) -> str:
        """Gera URL assinada temporária para download seguro diretamente do storage."""
