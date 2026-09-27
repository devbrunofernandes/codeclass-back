from app.core.config import settings
from app.infrastructure.storage.base import StorageProvider
from app.infrastructure.storage.supabase_provider import SupabaseStorageProvider


def get_storage_provider() -> StorageProvider:
    """Factory para instanciar o provedor de storage ativo de acordo com as configurações."""
    provider_name = (settings.STORAGE_PROVIDER or "supabase").lower()

    if provider_name == "supabase":
        return SupabaseStorageProvider()

    raise ValueError(f"Provedor de storage não suportado: '{provider_name}'")
