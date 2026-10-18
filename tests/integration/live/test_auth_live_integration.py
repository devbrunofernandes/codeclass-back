import pytest

from app.models.organization import Organization
from app.models.user import User

pytestmark = pytest.mark.live("auth")


async def test_auth_when_account_lifecycle_should_sync_profile_rotate_tokens_and_delete(
    async_client, registered_org, db_session
):
    org = registered_org
    headers = org.auth_headers
    name = "Owner Live Atualizado"
    updated = await async_client.patch(
        "/api/v1/users/me", headers=headers, json={"full_name": name}
    )
    assert updated.status_code == 200, updated.text
    db_session.expire_all()
    user = await db_session.get(User, org.owner_uuid)
    assert user.full_name == name
    password = "LivePasswordUpdated123!"
    changed = await async_client.put(
        "/api/v1/users/me/password", headers=headers, json={"password": password}
    )
    assert changed.status_code == 204, changed.text
    old_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org.owner_email, "password": org.owner_password},
    )
    assert old_login.status_code == 401
    login = await async_client.post(
        "/api/v1/auth/login", json={"email": org.owner_email, "password": password}
    )
    assert login.status_code == 200, login.text
    refreshed = await async_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json()["refresh_token"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    headers = {"Authorization": f"Bearer {refreshed.json()['access_token']}"}
    profile = await async_client.get("/api/v1/users/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["full_name"] == name

    deleted = await async_client.delete(f"/api/v1/orgs/{org.org_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    db_session.expire_all()
    assert await db_session.get(User, org.owner_uuid) is None
    assert await db_session.get(Organization, org.org_uuid) is None
    revoked = await async_client.get("/api/v1/users/me", headers=headers)
    assert revoked.status_code == 401
    login = await async_client.post(
        "/api/v1/auth/login", json={"email": org.owner_email, "password": password}
    )
    assert login.status_code == 401
