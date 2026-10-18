from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AppException, NotFoundException, StorageError
from app.models.user import User
from app.services.storage_service import storage_service
from app.services.user_service import UserService


async def test_download_photo_when_present_should_return_url_and_expiration(
    profile_photo_provider, monkeypatch
):
    org, uid = uuid4(), uuid4()
    service = UserService()
    member = MagicMock()
    path = f"{org}/{uid}/profile.jpg"
    member.user.profile_photo_path = path
    monkeypatch.setattr(service, "get_user_in_org", AsyncMock(return_value=member))
    before = datetime.now(UTC)
    response = await service.download_profile_photo(uid, org, AsyncMock())
    after = datetime.now(UTC)
    assert response.profile_photo_url == "https://storage.example.com/signed"
    assert response.profile_photo_url_expires_at is not None
    assert (
        before + timedelta(seconds=3600)
        <= response.profile_photo_url_expires_at
        <= after + timedelta(seconds=3600)
    )
    profile_photo_provider.get_signed_url.assert_awaited_once_with(
        bucket="user-photos", path=path, expires_in=3600
    )


async def test_download_photo_when_signing_fails_should_propagate_error(
    profile_photo_provider, monkeypatch
):
    org, uid = uuid4(), uuid4()
    service = UserService()
    member = MagicMock()
    member.user.profile_photo_path = f"{org}/{uid}/profile.jpg"
    monkeypatch.setattr(service, "get_user_in_org", AsyncMock(return_value=member))
    profile_photo_provider.get_signed_url.side_effect = StorageError("Unavailable", 502)
    with pytest.raises(StorageError) as error:
        await service.download_profile_photo(uid, org, AsyncMock())
    assert error.value.status_code == 502


async def test_upload_photo_when_user_missing_should_not_write_storage(
    profile_photo_provider,
):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute.return_value = result
    with pytest.raises(NotFoundException):
        await UserService().upload_profile_photo(uuid4(), uuid4(), MagicMock(), db)
    profile_photo_provider.upload_file.assert_not_awaited()


async def test_download_photo_when_path_crosses_tenant_should_reject(
    profile_photo_provider, monkeypatch
):
    service = UserService()
    member = MagicMock()
    member.user.profile_photo_path = f"{uuid4()}/{uuid4()}/profile.jpg"
    monkeypatch.setattr(service, "get_user_in_org", AsyncMock(return_value=member))
    with pytest.raises(NotFoundException):
        await service.download_profile_photo(uuid4(), uuid4(), AsyncMock())
    profile_photo_provider.get_signed_url.assert_not_awaited()


async def test_upload_photo_when_storage_fails_should_preserve_database(monkeypatch):
    user = User(
        id=uuid4(), email="a@test.com", full_name="Test", profile_photo_path=None
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute.return_value = result
    monkeypatch.setattr(
        storage_service,
        "upload_profile_photo",
        AsyncMock(side_effect=StorageError("unavailable", 500)),
    )
    with pytest.raises(StorageError):
        await UserService().upload_profile_photo(user.id, uuid4(), MagicMock(), db)
    db.commit.assert_not_awaited()
    assert user.profile_photo_path is None


@pytest.mark.parametrize("concurrent_committed", [False, True])
async def test_upload_photo_when_commit_fails_should_compensate_without_deleting_concurrent_photo(
    profile_photo_provider, monkeypatch, concurrent_committed
):
    org, uid = uuid4(), uuid4()
    path = f"{org}/{uid}/profile.jpg"
    user = User(id=uid, email="a@test.com", full_name="Test", profile_photo_path=None)
    current = User(
        id=uid,
        email="a@test.com",
        full_name="Test",
        profile_photo_path=path if concurrent_committed else None,
    )
    first, second = MagicMock(), MagicMock()
    first.scalar_one_or_none.return_value = user
    second.scalar_one_or_none.return_value = current
    db = AsyncMock()
    db.execute.side_effect = [first, second]
    db.commit.side_effect = RuntimeError("commit failed")
    monkeypatch.setattr(
        storage_service, "upload_profile_photo", AsyncMock(return_value=path)
    )
    with pytest.raises(AppException):
        await UserService().upload_profile_photo(uid, org, MagicMock(), db)
    assert db.rollback.await_count == 2
    if concurrent_committed:
        profile_photo_provider.delete_file.assert_not_awaited()
    else:
        profile_photo_provider.delete_file.assert_awaited_once_with(
            bucket="user-photos", path=path
        )
