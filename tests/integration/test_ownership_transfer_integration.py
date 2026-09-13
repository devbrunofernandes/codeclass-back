import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import OrgContext


@pytest.mark.asyncio
async def test_transfer_organization_ownership_to_teacher(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Valida a transferência de titularidade e rebaixamento automático do antigo dono para admin."""
    uid = uuid.uuid4().hex[:6]
    # Cadastra o professor que receberá a titularidade
    prof_res = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": f"novo_dono_{uid}@codeclass-int.com",
            "full_name": f"Novo Dono {uid}",
            "password": "senhaSegura123!",
            "role": "teacher",
        },
    )
    assert prof_res.status_code == 201
    new_owner_id = prof_res.json()["user_id"]
    registered_org.track_user(new_owner_id)

    # Transfere titularidade
    transfer_res = await async_client.put(
        f"/api/v1/orgs/{registered_org.org_id}/owner",
        headers=registered_org.auth_headers,
        json={"new_owner_id": new_owner_id},
    )
    assert transfer_res.status_code == 200
    assert transfer_res.json()["owner_id"] == new_owner_id

    # Verifica papéis atualizados na listagem de membros
    list_res = await async_client.get(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
    )
    assert list_res.status_code == 200
    members_by_id = {m["user_id"]: m["role"] for m in list_res.json()}
    assert members_by_id[new_owner_id] == "owner"
    assert members_by_id[registered_org.owner_id] == "admin"


@pytest.mark.asyncio
async def test_transfer_ownership_to_non_member_fails(
    async_client: AsyncClient,
    registered_org: OrgContext,
) -> None:
    """Garante que não é possível transferir a organização para quem não é membro."""
    fake_id = str(uuid.uuid4())
    transfer_res = await async_client.put(
        f"/api/v1/orgs/{registered_org.org_id}/owner",
        headers=registered_org.auth_headers,
        json={"new_owner_id": fake_id},
    )
    assert transfer_res.status_code == 404
