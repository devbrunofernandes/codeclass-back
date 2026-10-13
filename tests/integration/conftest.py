"""Configuração de testes de integração e re-export de fixtures reais de Supabase Auth."""

import pytest

from tests.fixtures.integration import OrgContext, registered_org

__all__ = ["OrgContext", "registered_org"]


@pytest.fixture(autouse=True)
def isolate_integration_database(
    cleanup_database: None,
    override_runner_provider: object,
    mock_ai_service: object,
) -> None:
    """Garante limpeza antes e depois de cada integração."""
