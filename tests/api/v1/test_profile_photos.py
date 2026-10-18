from uuid import uuid4

import pytest


async def test_openapi_when_user_schemas_exposed_should_omit_internal_photo_path(
    async_client,
):
    response = await async_client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]
    for name in ("UserResponse", "CurrentUserProfileResponse", "ProfilePhotoResponse"):
        assert "profile_photo_path" not in schemas[name]["properties"]
        assert "profile_photo_url" in schemas[name]["properties"]
    assert "ProfilePhotoDownloadResponse" not in schemas
    for route, method in [
        ("/api/v1/users/me/photo", "put"),
        ("/api/v1/users/me/photo/download", "get"),
        ("/api/v1/users/{user_id}/photo/download", "get"),
    ]:
        schema = response.json()["paths"][route][method]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert schema["$ref"] == "#/components/schemas/ProfilePhotoResponse"


@pytest.mark.parametrize("own_photo", [True, False])
async def test_photo_download_when_present_should_share_upload_contract(
    async_client, tenant, profile_photo_provider, profile_photo_bytes, own_photo
):
    uploaded = await async_client.put(
        "/api/v1/users/me/photo",
        headers=tenant.student.auth_headers,
        files={"file": ("photo.png", profile_photo_bytes, "image/png")},
    )
    assert uploaded.status_code == 200
    target = "me" if own_photo else str(tenant.student.user.id)
    headers = tenant.student.auth_headers if own_photo else tenant.teacher.auth_headers
    response = await async_client.get(
        f"/api/v1/users/{target}/photo/download", headers=headers
    )
    assert response.status_code == 200
    assert (
        set(response.json())
        == set(uploaded.json())
        == {"profile_photo_url", "profile_photo_url_expires_at"}
    )
    assert response.json()["profile_photo_url"] == "https://storage.example.com/signed"
    assert response.json()["profile_photo_url_expires_at"] is not None


@pytest.mark.parametrize("role", ["owner", "admin", "teacher", "student"])
async def test_upload_photo_when_active_member_should_return_url_without_internal_path(
    async_client, tenant, profile_photo_provider, profile_photo_bytes, role
):
    member = getattr(tenant, role)
    response = await async_client.put(
        "/api/v1/users/me/photo",
        headers=member.auth_headers,
        files={"file": ("photo.png", profile_photo_bytes, "image/png")},
    )
    assert response.status_code == 200
    assert set(response.json()) == {"profile_photo_url", "profile_photo_url_expires_at"}
    assert response.json()["profile_photo_url"] == "https://storage.example.com/signed"
    profile = await async_client.get("/api/v1/users/me", headers=member.auth_headers)
    assert "profile_photo_path" not in profile.json()
    assert profile.json()["profile_photo_url"] == "https://storage.example.com/signed"
    assert profile.json()["profile_photo_url_expires_at"] is not None


async def test_profile_without_photo_should_return_null_url_without_storage(
    async_client, tenant, profile_photo_provider
):
    response = await async_client.get(
        "/api/v1/users/me", headers=tenant.owner.auth_headers
    )
    assert response.status_code == 200
    assert response.json()["profile_photo_url"] is None
    assert response.json()["profile_photo_url_expires_at"] is None
    assert "profile_photo_path" not in response.json()
    profile_photo_provider.get_signed_urls.assert_not_awaited()


async def test_list_members_with_photos_should_sign_page_in_single_call(
    async_client, tenant, db_session, profile_photo_provider
):
    for member in (tenant.student, tenant.teacher):
        member.user.profile_photo_path = f"{tenant.org.id}/{member.user.id}/profile.jpg"
    await db_session.commit()
    response = await async_client.get(
        f"/api/v1/orgs/{tenant.org.id}/members", headers=tenant.owner.auth_headers
    )
    assert response.status_code == 200
    photos = [item for item in response.json() if item["profile_photo_url"]]
    assert len(photos) == 2
    assert all(item["profile_photo_url_expires_at"] for item in photos)
    assert all("profile_photo_path" not in item for item in response.json())
    profile_photo_provider.get_signed_urls.assert_awaited_once()
    assert len(profile_photo_provider.get_signed_urls.call_args.kwargs["paths"]) == 2


async def test_member_profile_with_photo_should_include_url(
    async_client, tenant, db_session, profile_photo_provider
):
    tenant.student.user.profile_photo_path = (
        f"{tenant.org.id}/{tenant.student.user.id}/profile.jpg"
    )
    await db_session.commit()
    response = await async_client.get(
        f"/api/v1/users/{tenant.student.user.id}", headers=tenant.teacher.auth_headers
    )
    assert response.status_code == 200
    assert response.json()["profile_photo_url"] == "https://storage.example.com/signed"
    assert "profile_photo_path" not in response.json()


async def test_profile_when_storage_unavailable_should_still_return_user(
    async_client, tenant, db_session, profile_photo_provider
):
    from app.core.exceptions import StorageError

    tenant.owner.user.profile_photo_path = (
        f"{tenant.org.id}/{tenant.owner.user.id}/profile.jpg"
    )
    await db_session.commit()
    profile_photo_provider.get_signed_urls.side_effect = StorageError(
        "Unavailable", 502
    )
    response = await async_client.get(
        "/api/v1/users/me", headers=tenant.owner.auth_headers
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(tenant.owner.user.id)
    assert response.json()["profile_photo_url"] is None


async def test_login_with_photo_should_return_download_url_after_authentication(
    async_client, tenant, db_session, profile_photo_provider, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.infrastructure.auth import auth_service

    tenant.owner.user.profile_photo_path = (
        f"{tenant.org.id}/{tenant.owner.user.id}/profile.jpg"
    )
    await db_session.commit()
    monkeypatch.setattr(
        auth_service,
        "sign_in_with_password",
        AsyncMock(
            return_value={
                "user_id": tenant.owner.user.id,
                "access_token": "token",
                "refresh_token": None,
            }
        ),
    )
    response = await async_client.post(
        "/api/v1/auth/login",
        json={"email": tenant.owner.user.email, "password": "password"},
    )
    assert response.status_code == 200
    assert (
        response.json()["user"]["profile_photo_url"]
        == "https://storage.example.com/signed"
    )
    assert response.json()["user"]["profile_photo_url_expires_at"] is not None
    assert "profile_photo_path" not in response.json()["user"]


async def test_update_profile_with_photo_should_preserve_url(
    async_client, tenant, db_session, profile_photo_provider, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.infrastructure.auth import auth_service

    tenant.owner.user.profile_photo_path = (
        f"{tenant.org.id}/{tenant.owner.user.id}/profile.jpg"
    )
    await db_session.commit()
    monkeypatch.setattr(auth_service, "update_auth_user", AsyncMock())
    response = await async_client.patch(
        "/api/v1/users/me",
        headers=tenant.owner.auth_headers,
        json={"full_name": "Novo Nome"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Novo Nome"
    assert response.json()["profile_photo_url"] == "https://storage.example.com/signed"
    assert "profile_photo_path" not in response.json()


@pytest.mark.parametrize(
    "method,url",
    [
        ("put", "/api/v1/users/me/photo"),
        ("get", "/api/v1/users/me/photo/download"),
        ("get", f"/api/v1/users/{uuid4()}/photo/download"),
    ],
)
async def test_photo_when_unauthenticated_should_return_401(async_client, method, url):
    assert (await async_client.request(method, url)).status_code == 401


async def test_upload_photo_when_missing_file_should_return_422(async_client, tenant):
    response = await async_client.put(
        "/api/v1/users/me/photo", headers=tenant.owner.auth_headers
    )
    assert response.status_code == 422


async def test_photo_when_missing_or_invalid_user_should_return_404_or_422(
    async_client, tenant
):
    for target, status in [("me", 404), (str(uuid4()), 404), ("invalid", 422)]:
        response = await async_client.get(
            f"/api/v1/users/{target}/photo/download", headers=tenant.owner.auth_headers
        )
        assert response.status_code == status


async def test_photo_when_cross_tenant_should_return_404(
    async_client, tenant, create_tenant, profile_photo_provider
):
    other = await create_tenant("Other")
    response = await async_client.get(
        f"/api/v1/users/{other.owner.user.id}/photo/download",
        headers=tenant.owner.auth_headers,
    )
    assert response.status_code == 404
    profile_photo_provider.get_signed_url.assert_not_awaited()


@pytest.mark.parametrize("method,suffix", [("put", "photo"), ("get", "photo/download")])
async def test_photo_when_inactive_should_return_403(
    async_client, tenant, db_session, method, suffix
):
    tenant.student.member.is_active = False
    await db_session.commit()
    response = await async_client.request(
        method, f"/api/v1/users/me/{suffix}", headers=tenant.student.auth_headers
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "data,mime,status",
    [
        (b"", "image/png", 400),
        (b"not an image", "image/png", 400),
        (b"<svg/>", "image/svg+xml", 400),
        (b"x" * (5 * 1024 * 1024 + 1), "image/png", 413),
    ],
    ids=["empty", "corrupt", "svg", "oversized"],
)
async def test_upload_photo_when_invalid_should_return_error_and_preserve_state(
    async_client, tenant, db_session, profile_photo_provider, data, mime, status
):
    response = await async_client.put(
        "/api/v1/users/me/photo",
        headers=tenant.owner.auth_headers,
        files={"file": ("photo", data, mime)},
    )
    assert response.status_code == status
    await db_session.refresh(tenant.owner.user)
    assert tenant.owner.user.profile_photo_path is None
    profile_photo_provider.upload_file.assert_not_awaited()
