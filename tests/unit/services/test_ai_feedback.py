import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import BadRequestException, NotFoundException
from app.models.enums import SubmissionStatus
from app.models.submission import Submission, SubmissionAiInsight
from app.schemas.submission import SubmissionAiFeedbackRequest
from app.services.submission.evaluation_service import SubmissionEvaluationService


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["in_progress", "failed"])
async def test_save_feedback_when_insight_unavailable_should_reject(status):
    submission = Submission(id=uuid.uuid4(), status=SubmissionStatus.AWAITING_REVIEW)
    insight = SubmissionAiInsight(status=status)
    db = AsyncMock()
    db.scalar.side_effect = [submission, insight]
    with pytest.raises(BadRequestException):
        await SubmissionEvaluationService().save_ai_feedback(
            submission,
            SubmissionAiFeedbackRequest(feedback_positive=True, feedback_details=None),
            db,
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_submission", [True, False])
async def test_save_feedback_when_resource_missing_should_reject(missing_submission):
    submission = Submission(id=uuid.uuid4(), status=SubmissionStatus.AWAITING_REVIEW)
    db = AsyncMock()
    db.scalar.side_effect = [None] if missing_submission else [submission, None]
    with pytest.raises(NotFoundException):
        await SubmissionEvaluationService().save_ai_feedback(
            submission,
            SubmissionAiFeedbackRequest(feedback_positive=None, feedback_details=None),
            db,
        )
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_feedback_when_completed_should_commit_without_changing_grade():
    submission = Submission(id=uuid.uuid4(), status=SubmissionStatus.PUBLISHED)
    insight = SubmissionAiInsight(status="completed", reasoning="Parecer original")
    db = AsyncMock()
    db.scalar.side_effect = [submission, insight]
    result = await SubmissionEvaluationService().save_ai_feedback(
        submission,
        SubmissionAiFeedbackRequest(feedback_positive=False, feedback_details="Erro"),
        db,
    )
    assert result.feedback_positive is False
    assert result.feedback_details == "Erro"
    assert result.reasoning == "Parecer original"
    assert submission.status == SubmissionStatus.PUBLISHED
    db.commit.assert_awaited_once()
