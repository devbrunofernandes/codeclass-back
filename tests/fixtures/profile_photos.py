import io

import pytest
from PIL import Image


@pytest.fixture
def profile_photo_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def profile_photo_provider(monkeypatch, mock_storage_provider):
    from app.services.storage_service import storage_service

    monkeypatch.setattr(storage_service, "_provider", mock_storage_provider)
    return mock_storage_provider


@pytest.fixture
async def real_profile_photo_provider(monkeypatch, tenant):
    from app.infrastructure.storage.supabase_provider import SupabaseStorageProvider
    from app.services.storage_service import storage_service

    provider = SupabaseStorageProvider()
    monkeypatch.setattr(storage_service, "_provider", provider)
    try:
        yield provider
    finally:
        await provider.delete_file(
            bucket="user-photos",
            path=f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg",
        )
