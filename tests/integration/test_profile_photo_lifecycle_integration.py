import asyncio
import io
from unittest.mock import AsyncMock

import httpx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StorageError
from app.models.user import User


async def test_profile_photo_when_replaced_should_keep_one_object_and_persist_path(
    async_client, tenant, db_session, profile_photo_provider, profile_photo_bytes
):
    objects = {}

    async def upload(**kwargs):
        objects[kwargs["path"]] = kwargs["file"].read()

    profile_photo_provider.upload_file.side_effect = upload
    for filename in ("first.png", "replacement.png"):
        response = await async_client.put(
            "/api/v1/users/me/photo",
            headers=tenant.student.auth_headers,
            files={"file": (filename, profile_photo_bytes, "image/png")},
        )
        assert response.status_code == 200
        assert "profile_photo_path" not in response.json()
        path = f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg"
        await db_session.refresh(tenant.student.user)
        assert (
            await db_session.get(User, tenant.student.user.id)
        ).profile_photo_path == path
        assert list(objects) == [path]
    for target in ("me", str(tenant.student.user.id)):
        headers = (
            tenant.student.auth_headers
            if target == "me"
            else tenant.teacher.auth_headers
        )
        download = await async_client.get(
            f"/api/v1/users/{target}/photo/download", headers=headers
        )
        assert download.status_code == 200
        assert set(download.json()) == {
            "profile_photo_url",
            "profile_photo_url_expires_at",
        }
        assert download.json()["profile_photo_url_expires_at"] is not None
        assert (
            download.json()["profile_photo_url"] == "https://storage.example.com/signed"
        )


async def test_profile_photo_when_real_storage_should_replace_and_download_image(
    async_client, tenant, db_session, real_profile_photo_provider, profile_photo_bytes
):
    for name in ("first.png", "second.png"):
        response = await async_client.put(
            "/api/v1/users/me/photo",
            headers=tenant.student.auth_headers,
            files={"file": (name, profile_photo_bytes, "image/png")},
        )
        assert response.status_code == 200, response.text
    await db_session.refresh(tenant.student.user)
    assert "profile_photo_path" not in response.json()
    assert (
        tenant.student.user.profile_photo_path
        == f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg"
    )
    files = await real_profile_photo_provider.list_files(
        "user-photos", f"{tenant.org.id}/{tenant.student.user.id}"
    )
    assert [item["name"] for item in files] == ["profile.jpg"]
    response = await async_client.get(
        f"/api/v1/users/{tenant.student.user.id}/photo/download",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    async with httpx.AsyncClient() as client:
        downloaded = await client.get(response.json()["profile_photo_url"])
    assert downloaded.status_code == 200
    with Image.open(io.BytesIO(downloaded.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (4, 4)


async def test_profile_photo_when_concurrent_uploads_should_preserve_single_path(
    async_client, tenant, db_session, profile_photo_provider, profile_photo_bytes
):
    async def upload(name):
        return await async_client.put(
            "/api/v1/users/me/photo",
            headers=tenant.student.auth_headers,
            files={"file": (name, profile_photo_bytes, "image/png")},
        )

    responses = await asyncio.gather(upload("first.png"), upload("second.png"))
    assert [response.status_code for response in responses] == [200, 200]
    assert all("profile_photo_path" not in response.json() for response in responses)
    assert all(response.json()["profile_photo_url"] for response in responses)
    await db_session.refresh(tenant.student.user)
    assert (
        tenant.student.user.profile_photo_path
        == f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg"
    )
    calls = profile_photo_provider.upload_file.await_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["path"] == calls[1].kwargs["path"]


async def test_profile_photo_when_first_commit_fails_should_rollback_and_cleanup(
    async_client,
    tenant,
    db_session,
    profile_photo_provider,
    profile_photo_bytes,
    monkeypatch,
):
    with monkeypatch.context() as patch:
        patch.setattr(
            AsyncSession, "commit", AsyncMock(side_effect=RuntimeError("commit failed"))
        )
        response = await async_client.put(
            "/api/v1/users/me/photo",
            headers=tenant.student.auth_headers,
            files={"file": ("photo.png", profile_photo_bytes, "image/png")},
        )
    assert response.status_code == 500
    await db_session.refresh(tenant.student.user)
    assert tenant.student.user.profile_photo_path is None
    profile_photo_provider.delete_file.assert_awaited_once_with(
        bucket="user-photos",
        path=f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg",
    )


async def test_profile_photo_when_replacement_storage_fails_should_keep_existing_path(
    async_client, tenant, db_session, profile_photo_provider, profile_photo_bytes
):
    response = await async_client.put(
        "/api/v1/users/me/photo",
        headers=tenant.student.auth_headers,
        files={"file": ("photo.png", profile_photo_bytes, "image/png")},
    )
    assert response.status_code == 200
    await db_session.refresh(tenant.student.user)
    path = tenant.student.user.profile_photo_path
    profile_photo_provider.upload_file.side_effect = StorageError("unavailable", 500)
    failed = await async_client.put(
        "/api/v1/users/me/photo",
        headers=tenant.student.auth_headers,
        files={"file": ("replacement.png", profile_photo_bytes, "image/png")},
    )
    assert failed.status_code == 500
    await db_session.refresh(tenant.student.user)
    assert tenant.student.user.profile_photo_path == path
    profile_photo_provider.delete_file.assert_not_awaited()


async def test_photo_urls_when_profile_and_members_requested_should_use_real_batch_signing(
    async_client, tenant, db_session, real_profile_photo_provider, profile_photo_bytes
):
    response = await async_client.put(
        "/api/v1/users/me/photo",
        headers=tenant.student.auth_headers,
        files={"file": ("photo.png", profile_photo_bytes, "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["profile_photo_url"]
    await db_session.refresh(tenant.student.user)
    path = tenant.student.user.profile_photo_path
    for endpoint, headers in [
        ("/api/v1/users/me", tenant.student.auth_headers),
        (f"/api/v1/users/{tenant.student.user.id}", tenant.teacher.auth_headers),
    ]:
        response = await async_client.get(endpoint, headers=headers)
        assert response.status_code == 200
        assert response.json()["profile_photo_url_expires_at"]
        assert "profile_photo_path" not in response.json()
        async with httpx.AsyncClient() as client:
            downloaded = await client.get(response.json()["profile_photo_url"])
        assert downloaded.status_code == 200
        with Image.open(io.BytesIO(downloaded.content)) as image:
            assert image.format == "JPEG"
    members = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members", headers=tenant.teacher.auth_headers
    )
    assert members.status_code == 200
    photo = next(
        item
        for item in members.json()
        if item["user_id"] == str(tenant.student.user.id)
    )
    assert photo["profile_photo_url"]
    await db_session.refresh(tenant.student.user)
    assert tenant.student.user.profile_photo_path == path
