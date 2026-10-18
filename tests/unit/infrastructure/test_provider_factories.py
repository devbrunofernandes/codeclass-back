"""Rejeição genérica de estratégias não suportadas, sem instanciar adaptadores."""

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.infrastructure.ai.factory import get_ai_provider
from app.infrastructure.realtime.pubsub.factory import get_pubsub_broker
from app.infrastructure.runner.factory import get_runner_provider
from app.infrastructure.storage.factory import get_storage_provider


def test_get_ai_provider_unsupported_raises_error():
    with (
        patch(
            "app.infrastructure.ai.factory.settings.AI_PROVIDER", "unsupported_provider"
        ),
        pytest.raises(ValueError, match="Provedor de IA não suportado"),
    ):
        get_ai_provider()


def test_get_storage_provider_unsupported(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "unsupported_storage")
    with pytest.raises(ValueError, match="Provedor de storage não suportado"):
        get_storage_provider()


def test_factory_raises_for_unsupported_provider() -> None:
    with (
        patch.object(settings, "RUNNER_PROVIDER", "unsupported_engine"),
        pytest.raises(ValueError, match="Provedor de runner não suportado"),
    ):
        get_runner_provider()


def test_get_pubsub_broker_unsupported_raises_value_error() -> None:
    with pytest.raises(ValueError, match="não suportado"):
        get_pubsub_broker("unsupported_broker_xyz")
