"""Verifica o contrato interno de sincronização do adaptador Supabase Auth."""

from sqlalchemy import text


async def test_profile_when_name_updated_should_sync_supabase_user_metadata(
    async_client, registered_org, db_session
):
    name = "Owner Supabase Atualizado"
    response = await async_client.patch(
        "/api/v1/users/me",
        headers=registered_org.auth_headers,
        json={"full_name": name},
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == name
    auth_name = await db_session.scalar(
        text("SELECT raw_user_meta_data->>'full_name' FROM auth.users WHERE id = :id"),
        {"id": registered_org.owner_uuid},
    )
    assert auth_name == name
