"""Requisitos de configuração dos adaptadores usados nos testes live."""

from types import SimpleNamespace

import pytest

from tests.fixtures.live import validate_live_settings


@pytest.mark.parametrize("service", ["ai", "runner", "storage", "auth"])
def test_live_configuration_when_required_setting_missing_should_fail(service):
    config = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        SUPABASE_URL="",
        SUPABASE_KEY="",
        AI_API_KEY="",
        RUNNER_PROVIDER="judge0",
        RUNNER_API_URL="https://runner.example",
        RUNNER_API_KEY="",
    )
    with pytest.raises(pytest.UsageError):
        validate_live_settings(service, config)


@pytest.mark.parametrize("provider", ["piston", "PISTON"])
def test_live_runner_when_local_piston_has_no_key_should_allow(provider):
    config = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        RUNNER_PROVIDER=provider,
        RUNNER_API_URL="http://localhost:2000",
        RUNNER_API_KEY="",
    )
    validate_live_settings("runner", config)


def test_live_runner_when_judge0_has_no_key_should_fail():
    config = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        RUNNER_PROVIDER="judge0",
        RUNNER_API_URL="https://runner.example",
        RUNNER_API_KEY="",
    )
    with pytest.raises(pytest.UsageError, match="RUNNER_API_KEY"):
        validate_live_settings("runner", config)


@pytest.mark.parametrize("service", ["ai", "runner", "storage", "auth"])
def test_live_configuration_when_complete_should_allow(service):
    config = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        SUPABASE_URL="http://localhost:54321",
        SUPABASE_KEY="test",
        AI_API_KEY="test",
        RUNNER_PROVIDER="judge0",
        RUNNER_API_URL="https://runner.example",
        RUNNER_API_KEY="test",
    )
    validate_live_settings(service, config)
