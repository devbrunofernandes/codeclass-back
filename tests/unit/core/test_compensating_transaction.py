from unittest.mock import AsyncMock

import pytest

from app.core.compensating_transaction import CompensatingTransaction


@pytest.mark.asyncio
async def test_compensating_transaction_success_does_not_execute_actions() -> None:
    mock_db = AsyncMock()
    action = AsyncMock()

    async with CompensatingTransaction(db=mock_db) as tx:
        tx.register(action, 1, key="value")

    mock_db.rollback.assert_not_called()
    action.assert_not_called()


@pytest.mark.asyncio
async def test_compensating_transaction_failure_executes_actions_in_lifo_order() -> (
    None
):
    mock_db = AsyncMock()
    execution_order: list[str] = []

    async def action_one() -> None:
        execution_order.append("first")

    async def action_two() -> None:
        execution_order.append("second")

    with pytest.raises(ValueError, match="Boom"):
        async with CompensatingTransaction(db=mock_db) as tx:
            tx.register(action_one, name="action_one")
            tx.register(action_two, name="action_two")
            raise ValueError("Boom")

    mock_db.rollback.assert_awaited_once()
    assert execution_order == ["second", "first"]


@pytest.mark.asyncio
async def test_compensating_transaction_failure_continues_on_action_error() -> None:
    mock_db = AsyncMock()
    action_one = AsyncMock()
    failing_action = AsyncMock(side_effect=RuntimeError("Action failed"))

    with pytest.raises(KeyError):
        async with CompensatingTransaction(db=mock_db) as tx:
            tx.register(action_one)
            tx.register(failing_action)
            raise KeyError("Trigger error")

    mock_db.rollback.assert_awaited_once()
    failing_action.assert_awaited_once()
    action_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_compensating_transaction_failure_continues_on_db_rollback_error() -> (
    None
):
    mock_db = AsyncMock()
    mock_db.rollback.side_effect = RuntimeError("DB rollback failure")
    action = AsyncMock()

    with pytest.raises(ZeroDivisionError):
        async with CompensatingTransaction(db=mock_db) as tx:
            tx.register(action)
            raise ZeroDivisionError("Math error")

    mock_db.rollback.assert_awaited_once()
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_compensating_transaction_cancel_clears_actions() -> None:
    mock_db = AsyncMock()
    action = AsyncMock()

    with pytest.raises(RuntimeError):
        async with CompensatingTransaction(db=mock_db) as tx:
            tx.register(action)
            tx.cancel()
            raise RuntimeError("Cancel test")

    mock_db.rollback.assert_awaited_once()
    action.assert_not_called()


@pytest.mark.asyncio
async def test_compensating_transaction_supports_sync_and_async_actions() -> None:
    mock_db = AsyncMock()
    sync_called = False
    async_mock = AsyncMock()

    def sync_action(arg: str) -> None:
        nonlocal sync_called
        sync_called = True

    with pytest.raises(ValueError):
        async with CompensatingTransaction(db=mock_db) as tx:
            tx.register(sync_action, "test_arg")
            tx.register(async_mock, "async_arg")
            raise ValueError("Error")

    assert sync_called is True
    async_mock.assert_awaited_once_with("async_arg")


@pytest.mark.asyncio
async def test_compensating_transaction_explicit_rollback_idempotent() -> None:
    mock_db = AsyncMock()
    action = AsyncMock()

    tx = CompensatingTransaction(db=mock_db)
    tx.register(action)

    await tx.rollback()
    await tx.rollback()

    mock_db.rollback.assert_awaited_once()
    action.assert_awaited_once()


@pytest.mark.asyncio
async def test_compensating_transaction_without_db() -> None:
    action = AsyncMock()

    with pytest.raises(ValueError):
        async with CompensatingTransaction() as tx:
            tx.register(action)
            raise ValueError("Error")

    action.assert_awaited_once()
