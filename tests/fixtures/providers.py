"""Fixtures específicas das implementações de infraestrutura."""

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from app.infrastructure.auth.supabase_auth import AuthService


@pytest.fixture
def auth_svc() -> AuthService:
    from app.infrastructure.auth.supabase_auth import AuthService

    return AuthService()


def required_provider_settings(service: str, config: Any) -> tuple[str, ...]:
    """Declara as credenciais e os endereços exigidos pelos adaptadores atuais."""
    if service in {"storage", "auth"}:
        return ("SUPABASE_URL", "SUPABASE_KEY")
    if service == "ai":
        return ("AI_API_KEY",)
    if service == "runner":
        if (config.RUNNER_PROVIDER or "judge0").lower() == "piston":
            return ("RUNNER_API_URL",)
        return ("RUNNER_API_URL", "RUNNER_API_KEY")
    return ()
