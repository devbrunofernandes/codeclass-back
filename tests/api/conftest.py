"""Isolamento PostgreSQL obrigatório para testes de API."""

import pytest


@pytest.fixture(autouse=True)
def isolate_api_database(
    cleanup_database: None,
    override_runner_provider: object,
    mock_ai_service: object,
) -> None:
    """Ativa a limpeza inclusive para testes sem cliente ou sessão explícitos."""
