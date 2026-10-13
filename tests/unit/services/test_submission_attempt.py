import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.submission.ai_worker import SubmissionAiWorker


@pytest.mark.asyncio
async def test_worker_when_attempt_obsolete_should_skip_provider():
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    with (
        patch(
            "app.services.submission.ai_worker.async_session_maker",
            return_value=session,
        ),
        patch(
            "app.services.submission.ai_worker.ai_service.evaluate_submission",
            new_callable=AsyncMock,
        ) as provider,
    ):
        await SubmissionAiWorker().process_submission_ai_task(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        )
    provider.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_when_attempt_not_claimed_should_not_write_insights():
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.begin = MagicMock(return_value=AsyncMock())
    session.scalar.return_value = None
    with patch(
        "app.services.submission.ai_worker.async_session_maker", return_value=session
    ):
        await SubmissionAiWorker()._complete_attempt(
            uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), None, "obsolete error"
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_when_provider_cancelled_should_not_apply_fallback():
    import asyncio

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.expunge = MagicMock()
    sub = MagicMock()
    from app.models.enums import SubmissionStatus

    sub.status = SubmissionStatus.PENDING
    result = MagicMock()
    result.scalar_one_or_none.return_value = sub
    session.execute.return_value = result
    worker = SubmissionAiWorker()
    with (
        patch(
            "app.services.submission.ai_worker.async_session_maker",
            return_value=session,
        ),
        patch(
            "app.services.submission.ai_worker.ai_service.evaluate_submission",
            new_callable=AsyncMock,
        ) as provider,
        patch.object(worker, "_complete_attempt", new_callable=AsyncMock) as complete,
    ):
        provider.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await worker.process_submission_ai_task(
                uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            )
    complete.assert_not_awaited()


@pytest.mark.parametrize(
    "answer",
    [
        {"question_id": 2, "text_answer": "original"},
        {"question_id": 2, "text_answer": ""},
        {"question_id": 2, "text_answer": None},
        {"question_id": 2, "selected_option_id": "a"},
        {"question_id": 2, "selected_option_id": None},
        {"question_id": 2},
    ],
)
def test_questionnaire_draft_when_partial_answer_should_preserve_supplied_fields(
    answer,
):
    from app.schemas.submission import SubmissionDraftRequest

    request = SubmissionDraftRequest.model_validate({"content": {"answers": [answer]}})
    assert request.content.model_dump(exclude_unset=True) == {"answers": [answer]}
