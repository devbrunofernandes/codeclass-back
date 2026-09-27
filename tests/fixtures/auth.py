import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.infrastructure.auth import auth_service


@pytest.fixture
async def sample_user_and_org(
    async_client: AsyncClient,
    create_access_token: Callable[[uuid.UUID | str, str, str, timedelta | None], str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Cria uma organização e usuário proprietário de teste para autenticação."""
    owner_id = uuid.uuid4()
    slug = f"org-auth-{owner_id.hex[:6]}"
    email = f"auth_owner_{owner_id.hex[:6]}@example.com"
    monkeypatch.setattr(
        auth_service,
        "create_auth_user",
        AsyncMock(
            return_value={"id": owner_id, "email": email, "full_name": "Auth Owner"}
        ),
    )

    res = await async_client.post(
        "/api/v1/orgs",
        json={
            "name": "Org Auth Test",
            "slug": slug,
            "owner": {
                "email": email,
                "full_name": "Auth Owner",
                "password": "securepassword123",
            },
        },
    )
    assert res.status_code == 201
    org_id = res.json()["id"]
    token = create_access_token(owner_id, email, "Auth Owner", None)
    return {
        "org_id": org_id,
        "owner_id": owner_id,
        "email": email,
        "token": token,
        "slug": slug,
    }
