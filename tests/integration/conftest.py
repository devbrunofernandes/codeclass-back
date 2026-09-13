import contextlib
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
from httpx import AsyncClient

from app.services.auth_service import AuthError, auth_service


@dataclass
class OrgContext:
    org_id: str
    org_slug: str
    owner_id: str
    owner_email: str
    owner_password: str
    owner_name: str
    access_token: str
    refresh_token: str
    auth_headers: dict[str, str]
    created_user_ids: list[str] = field(default_factory=list)

    def track_user(self, user_id: str) -> None:
        self.created_user_ids.append(user_id)


@pytest.fixture
async def registered_org(async_client: AsyncClient) -> AsyncGenerator[OrgContext]:
    """Cria uma organização e Owner reais no Supabase Auth e Postgres para testes de integração."""
    unique_suffix = uuid.uuid4().hex[:8]
    org_slug = f"int-org-{unique_suffix}"
    owner_email = f"owner_{unique_suffix}@codeclass-int.com"
    owner_password = "senhaSegura123!"
    owner_name = f"Owner Int {unique_suffix}"

    # 1. Cadastro da Organização e Owner
    reg_payload = {
        "name": f"Universidade Integração {unique_suffix}",
        "slug": org_slug,
        "owner": {
            "email": owner_email,
            "full_name": owner_name,
            "password": owner_password,
        },
    }
    res_org = await async_client.post("/api/v1/orgs", json=reg_payload)
    assert res_org.status_code == 201, f"Falha no registro da org: {res_org.text}"
    org_data = res_org.json()
    org_id = org_data["id"]
    owner_id = org_data["owner_id"]

    # 2. Login do Owner no GoTrue real
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"email": owner_email, "password": owner_password},
    )
    assert login_res.status_code == 200, f"Falha no login do owner: {login_res.text}"
    login_data = login_res.json()
    access_token = login_data["access_token"]
    refresh_token = login_data["refresh_token"]

    context = OrgContext(
        org_id=org_id,
        org_slug=org_slug,
        owner_id=owner_id,
        owner_email=owner_email,
        owner_password=owner_password,
        owner_name=owner_name,
        access_token=access_token,
        refresh_token=refresh_token,
        auth_headers={"Authorization": f"Bearer {access_token}"},
        created_user_ids=[owner_id],
    )

    try:
        yield context
    finally:
        # Limpeza de todos os usuários criados no Supabase Auth
        for uid in context.created_user_ids:
            with contextlib.suppress(AuthError):
                await auth_service.delete_auth_user(uid)
