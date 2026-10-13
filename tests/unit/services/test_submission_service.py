import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    BadRequestException,
)
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, SubmissionStatus
from app.services.submission import (
    SubmissionAiWorker,
    SubmissionLifecycleService,
    submission_query_service,
)


def test_grade_objective_questionnaire_when_all_correct():
    service = SubmissionLifecycleService()
    questions = [
        {"id": 1, "type": "choice", "points": 5.0, "correct_option_id": "b"},
        {"id": 2, "type": "choice", "points": 5.0, "correct_option_id": "a"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "b"},
        {"question_id": 2, "selected_option_id": "a"},
    ]

    grade, detailed = service.grade_objective_questions(questions, answers)
    assert grade == Decimal("10.00")
    assert len(detailed["questions_evaluation"]) == 2
    assert detailed["questions_evaluation"][0]["is_correct"] is True
    assert detailed["questions_evaluation"][1]["is_correct"] is True


def test_grade_objective_questionnaire_when_partial_correct():
    service = SubmissionLifecycleService()
    questions = [
        {"id": 1, "type": "choice", "points": 4.0, "correct_option_id": "c"},
        {"id": 2, "type": "choice", "points": 6.0, "correct_option_id": "d"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "c"},
        {"question_id": 2, "selected_option_id": "a"},  # Errada
    ]

    grade, detailed = service.grade_objective_questions(questions, answers)
    assert grade == Decimal("4.00")
    assert detailed["questions_evaluation"][0]["is_correct"] is True
    assert detailed["questions_evaluation"][1]["is_correct"] is False


def test_grade_objective_questionnaire_when_unanswered_question_should_score_zero():
    service = SubmissionLifecycleService()
    questions = [
        {"id": 1, "type": "choice", "points": 5.0, "correct_option_id": "a"},
        {"id": 2, "type": "choice", "points": 5.0, "correct_option_id": "b"},
    ]
    # O aluno respondeu apenas a questão 1
    answers = [{"question_id": 1, "selected_option_id": "a"}]

    grade, detailed = service.grade_objective_questions(questions, answers)
    assert grade == Decimal("5.00")
    assert len(detailed["questions_evaluation"]) == 2
    assert detailed["questions_evaluation"][0]["is_correct"] is True
    assert detailed["questions_evaluation"][1]["is_correct"] is False


def test_validate_code_submission_language_when_invalid_should_raise():
    service = SubmissionLifecycleService()
    allowed_langs = ["python3", "javascript"]

    with pytest.raises(BadRequestException):
        service.validate_code_content("c++", "int main() {}", allowed_langs)


def test_validate_code_submission_language_when_valid_should_pass():
    service = SubmissionLifecycleService()
    allowed_langs = ["python3", "javascript"]

    # Não deve levantar exceção
    service.validate_code_content("python3", "print(1)", allowed_langs)


@pytest.mark.asyncio
async def test_process_submission_ai_task_when_not_pending_should_skip():
    service = SubmissionAiWorker()
    sub_id = uuid.uuid4()

    mock_sub = MagicMock()
    mock_sub.status = SubmissionStatus.DRAFT
    mock_sub.assignment = MagicMock()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_sub
    mock_session.execute.return_value = mock_result

    with (
        patch(
            "app.services.submission.ai_worker.async_session_maker",
            return_value=mock_session,
        ),
        patch(
            "app.services.submission.ai_worker.ai_service.evaluate_submission",
            new_callable=AsyncMock,
        ) as mock_ai,
    ):
        mock_session.__aenter__.return_value = mock_session
        await service.process_submission_ai_task(sub_id, uuid.uuid4(), uuid.uuid4())

    mock_ai.assert_not_called()


@pytest.mark.asyncio
async def test_process_submission_ai_task_when_success_should_update_insight_and_status():
    service = SubmissionAiWorker()
    sub_id = uuid.uuid4()

    mock_sub = MagicMock()
    mock_sub.id = sub_id
    mock_sub.status = SubmissionStatus.PENDING
    mock_sub.content = {"code": "print(1)", "language": "python3"}
    mock_sub.assignment = MagicMock()
    mock_sub.ai_insight = None
    service._complete_attempt = AsyncMock()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.expunge = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_sub
    mock_session.execute.return_value = mock_result

    mock_insight_result = MagicMock()
    mock_insight_result.suggested_grade = 9.0
    mock_insight_result.max_grade = 10.0
    mock_insight_result.reasoning = "Excelente"
    mock_insight_result.strengths = ["Limpo"]
    mock_insight_result.improvements = []
    mock_insight_result.item_insights = None

    with (
        patch(
            "app.services.submission.ai_worker.async_session_maker",
            return_value=mock_session,
        ),
        patch(
            "app.services.submission.ai_worker.ai_service.evaluate_submission",
            new_callable=AsyncMock,
        ) as mock_ai,
    ):
        mock_session.__aenter__.return_value = mock_session
        mock_ai.return_value = mock_insight_result
        await service.process_submission_ai_task(sub_id, uuid.uuid4(), uuid.uuid4())

    service._complete_attempt.assert_awaited_once()
    assert service._complete_attempt.await_args.args[3] is mock_insight_result
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_submission_ai_task_when_failure_should_fallback_to_failed_and_awaiting_review():
    service = SubmissionAiWorker()
    sub_id = uuid.uuid4()

    mock_sub = MagicMock()
    mock_sub.id = sub_id
    mock_sub.status = SubmissionStatus.PENDING
    mock_sub.content = {"code": "print(1)", "language": "python3"}
    mock_sub.assignment = MagicMock()
    mock_sub.ai_insight = MagicMock()
    service._complete_attempt = AsyncMock()

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.expunge = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_sub
    mock_session.execute.return_value = mock_result

    with (
        patch(
            "app.services.submission.ai_worker.async_session_maker",
            return_value=mock_session,
        ),
        patch(
            "app.services.submission.ai_worker.ai_service.evaluate_submission",
            new_callable=AsyncMock,
        ) as mock_ai,
    ):
        mock_session.__aenter__.return_value = mock_session
        mock_ai.side_effect = RuntimeError("Gemini API rate limit exceeded")
        await service.process_submission_ai_task(sub_id, uuid.uuid4(), uuid.uuid4())

    service._complete_attempt.assert_awaited_once()
    assert service._complete_attempt.await_args.args[3] is None
    assert (
        "Gemini API rate limit exceeded" in service._complete_attempt.await_args.args[4]
    )


@pytest.mark.asyncio
async def test_submit_assignment_idempotency_when_draft_code_identical_should_not_enqueue_ai():
    from app.models.enums import ReleasePolicyType
    from app.schemas.submission import CodeSubmissionContent, SubmissionCreateRequest

    service = SubmissionLifecycleService()
    assignment = Assignment(
        title="Busca Binária",
        description="Teste",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={"languages": [{"name": "python3"}]},
    )
    assignment.deadline = None

    existing_sub = MagicMock()
    existing_sub.status = SubmissionStatus.DRAFT
    existing_sub.content = {"language": "python3", "code": "def search(): pass"}
    existing_sub.ai_insight = MagicMock()
    existing_sub.ai_insight.status = "completed"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_sub
    mock_db.execute.return_value = mock_result

    mock_bg = MagicMock()

    req = SubmissionCreateRequest(
        content=CodeSubmissionContent(language="python3", code="def search(): pass")
    )

    sub = await service.submit_assignment(
        assignment=assignment,
        student_id=uuid.uuid4(),
        request=req,
        db=mock_db,
        background_tasks=mock_bg,
    )

    assert sub.status == SubmissionStatus.AWAITING_REVIEW
    mock_bg.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_submit_assignment_when_draft_code_modified_should_enqueue_ai():
    from app.models.enums import ReleasePolicyType
    from app.schemas.submission import CodeSubmissionContent, SubmissionCreateRequest

    service = SubmissionLifecycleService()
    assignment = Assignment(
        title="Busca Binária",
        description="Teste",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={"languages": [{"name": "python3"}]},
    )
    assignment.deadline = None

    existing_sub = MagicMock()
    existing_sub.status = SubmissionStatus.DRAFT
    existing_sub.content = {"language": "python3", "code": "def old_code(): pass"}
    existing_sub.ai_insight = MagicMock()
    existing_sub.ai_insight.status = "completed"

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_sub
    mock_db.execute.return_value = mock_result

    mock_bg = MagicMock()

    req = SubmissionCreateRequest(
        content=CodeSubmissionContent(
            language="python3", code="def new_modified_code(): pass"
        )
    )

    sub = await service.submit_assignment(
        assignment=assignment,
        student_id=uuid.uuid4(),
        request=req,
        db=mock_db,
        background_tasks=mock_bg,
    )

    assert sub.status == SubmissionStatus.PENDING
    assert existing_sub.ai_insight.status == "in_progress"
    mock_bg.add_task.assert_called_once()


# --- Testes de Listagem e Avaliação Docente ---


@pytest.mark.asyncio
async def test_list_submissions_without_db_raises_value_error():
    with pytest.raises(ValueError, match="Database session is required"):
        await submission_query_service.list_submissions(db=None)


# --- Testes de Auto-save / Rascunhos (save_draft_submission) ---


# --- Testes de Reprocessamento de IA (retry_ai_evaluation) ---


def test_validate_code_content_empty_or_whitespace_raises_bad_request():
    service = SubmissionLifecycleService()
    with pytest.raises(
        BadRequestException, match="Linguagem e código são obrigatórios."
    ):
        service.validate_code_content("", "print('hi')", ["python"])

    with pytest.raises(
        BadRequestException, match="Linguagem e código são obrigatórios."
    ):
        service.validate_code_content("python", "   \n\t  ", ["python"])
