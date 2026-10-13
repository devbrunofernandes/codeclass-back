import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.core.config import settings


@pytest.fixture
def create_access_token() -> Callable[
    [uuid.UUID | str, str, str, timedelta | None], str
]:
    """Helper para emissão de JWT sintético compatível com GoTrue do Supabase."""

    def _create_token(
        user_id: uuid.UUID | str,
        email: str = "test@example.com",
        full_name: str = "Test User",
        expires_delta: timedelta | None = None,
    ) -> str:
        now = datetime.now(UTC)
        expire = now + (expires_delta or timedelta(hours=1))
        payload = {
            "sub": str(user_id),
            "email": email,
            "role": "authenticated",
            "user_metadata": {"full_name": full_name},
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
        secret = (
            settings.SUPABASE_JWT_SECRET
            or "super-secret-jwt-token-with-at-least-32-characters-long"
        )
        return jwt.encode(payload, secret, algorithm="HS256")

    return _create_token
