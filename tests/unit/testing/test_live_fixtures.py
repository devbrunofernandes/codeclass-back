"""Testa a seleção, substituição e restauração de dependências da suíte live."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.runner.base import CodeRunnerProvider
from tests.fixtures.live import validate_live_settings


def test_live_configuration_when_service_unknown_should_fail():
    with pytest.raises(pytest.UsageError, match="desconhecido"):
        validate_live_settings("unknown", SimpleNamespace())


@pytest.mark.parametrize("service", ["ai", "storage", "auth", "chat", None])
def test_runner_override_when_not_runner_live_should_keep_mock_and_restore(service):
    from app.services.runner_service import runner_service
    from tests.fixtures.runner import override_runner_provider

    marker = None if service is None else SimpleNamespace(args=(service,))
    request = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _: marker))
    previous = runner_service.provider
    mock = AsyncMock(spec=CodeRunnerProvider)
    override = override_runner_provider.__wrapped__(mock, request)
    assert next(override) is mock
    assert runner_service.provider is mock
    override.close()
    assert runner_service.provider is previous


def test_runner_override_when_runner_live_should_use_factory_and_restore(monkeypatch):
    from app.services.runner_service import runner_service
    from tests.fixtures.runner import override_runner_provider

    marker = SimpleNamespace(args=("runner",))
    request = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _: marker))
    previous = runner_service.provider
    selected = AsyncMock(spec=CodeRunnerProvider)
    monkeypatch.setattr(
        "app.infrastructure.runner.factory.get_runner_provider", lambda: selected
    )
    override = override_runner_provider.__wrapped__(
        AsyncMock(spec=CodeRunnerProvider), request
    )
    provider = next(override)
    assert provider is selected
    assert runner_service.provider is provider
    override.close()
    assert runner_service.provider is previous


@pytest.mark.parametrize("service", ["runner", "storage", "auth", "chat", None, "ai"])
def test_ai_override_when_selected_service_should_only_disable_for_ai(
    service, monkeypatch
):
    from unittest.mock import AsyncMock

    from tests.fixtures.submissions import mock_ai_service

    marker = None if service is None else SimpleNamespace(args=(service,))
    request = SimpleNamespace(node=SimpleNamespace(get_closest_marker=lambda _: marker))
    result = mock_ai_service.__wrapped__(request, monkeypatch)
    if service == "ai":
        assert result is None
    else:
        assert isinstance(result, AsyncMock)


@pytest.mark.parametrize("args", [(), ("unknown",), ("ai", "runner")])
def test_live_marker_when_invalid_should_reject(args):
    from tests.fixtures.live import live_service

    node = SimpleNamespace(get_closest_marker=lambda _: SimpleNamespace(args=args))
    with pytest.raises(pytest.UsageError, match="Use @pytest.mark.live"):
        live_service(node)


@pytest.mark.parametrize("database_url", ["", "postgresql+asyncpg://localhost/test"])
def test_live_configuration_when_database_setting_changes_should_validate(database_url):
    config = SimpleNamespace(DATABASE_URL=database_url)
    if database_url:
        validate_live_settings("chat", config)
    else:
        with pytest.raises(pytest.UsageError, match="DATABASE_URL"):
            validate_live_settings("chat", config)
