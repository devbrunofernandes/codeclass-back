"""Todo teste unitário deve executar sem rede."""

import pytest


@pytest.fixture(autouse=True)
def offline_unit_test(forbid_network: None) -> None:
    """Falha imediatamente diante de I/O de rede não mockado."""
