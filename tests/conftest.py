"""Ponto central de configuração do Pytest e carregamento de fixtures modulares."""

import pytest

pytest.register_assert_rewrite("tests.fixtures.tenants")
pytest.register_assert_rewrite("tests.fixtures.integration")

from tests.fixtures.tenants import TenantContext, TenantMember

pytest_plugins = [
    "tests.fixtures.core",
    "tests.fixtures.tenants",
    "tests.fixtures.classrooms",
    "tests.fixtures.assignments",
    "tests.fixtures.submissions",
    "tests.fixtures.chat",
    "tests.fixtures.integration",
    "tests.fixtures.runner",
    "tests.fixtures.auth",
]

__all__ = ["TenantContext", "TenantMember"]
