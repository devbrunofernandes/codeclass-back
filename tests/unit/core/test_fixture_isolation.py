from unittest.mock import AsyncMock

import pytest


def test_unit_scope_when_domain_test_runs_should_not_request_database(
    request: pytest.FixtureRequest,
) -> None:
    assert "cleanup_database" not in request.fixturenames
    assert "db_session" not in request.fixturenames
    assert "override_runner_provider" not in request.fixturenames


def test_network_when_unit_test_attempts_connection_should_fail() -> None:
    import socket

    with pytest.raises(AssertionError, match="tentou acessar a rede"):
        socket.create_connection(("localhost", 5432))


@pytest.mark.parametrize(
    "paths",
    [
        ["tests/unit", "tests/api", "tests/integration"],
        ["tests/integration", "tests/api", "tests/unit"],
    ],
)
def test_collection_when_suites_are_combined_should_preserve_fixture_scopes(
    paths: list[str],
) -> None:
    from tests.fixtures.isolation import collect_fixture_scopes

    collect_fixture_scopes(paths)


def test_collection_when_only_domain_is_selected_should_not_bootstrap_providers() -> (
    None
):
    from tests.fixtures.isolation import collect_fixture_scopes

    collect_fixture_scopes(["tests/unit/domain"], domain_only=True)


async def test_cleanup_when_test_body_fails_should_clean_before_and_after(
    cleanup_session_probe: tuple[AsyncMock, AsyncMock],
) -> None:
    from tests.fixtures.core import cleanup_database

    session, dispose = cleanup_session_probe
    cleanup = cleanup_database.__wrapped__()
    await anext(cleanup)
    assert session.commit.await_count == 1

    with pytest.raises(RuntimeError, match="falha do teste"):
        try:
            raise RuntimeError("falha do teste")
        finally:
            await cleanup.aclose()

    assert session.commit.await_count == 2
    dispose.assert_awaited_once()


async def test_cleanup_when_teardown_fails_should_dispose_engine(
    cleanup_session_probe: tuple[AsyncMock, AsyncMock],
) -> None:
    from tests.fixtures.core import cleanup_database

    session, dispose = cleanup_session_probe
    session.commit.side_effect = [None, RuntimeError("falha na limpeza")]
    cleanup = cleanup_database.__wrapped__()
    await anext(cleanup)

    with pytest.raises(RuntimeError, match="falha na limpeza"):
        await cleanup.aclose()

    dispose.assert_awaited_once()
