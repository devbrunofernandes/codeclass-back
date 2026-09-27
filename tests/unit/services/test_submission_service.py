import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.classroom import ClassroomStudent
from app.models.enums import AssignmentType, SubmissionStatus
from app.models.submission import Submission, SubmissionAiInsight
from app.models.user import User
from app.schemas.evaluation import SubmissionEvaluationRequest
from app.schemas.submission import (
    CodeSubmissionDraftContent,
    QuestionnaireSubmissionDraftContent,
    SubmissionDraftRequest,
)
from app.services.submission import (
    SubmissionAiWorker,
    SubmissionLifecycleService,
    submission_ai_worker,
    submission_evaluation_service,
    submission_lifecycle_service,
    submission_query_service,
)
from tests.fixtures.tenants import TenantContext


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
        await service.process_submission_ai_task(sub_id)

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

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
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
        await service.process_submission_ai_task(sub_id)

    assert mock_sub.status == SubmissionStatus.AWAITING_REVIEW
    assert mock_sub.ai_insight.status == "completed"
    assert mock_sub.ai_insight.suggested_grade == Decimal("9.0")
    assert mock_sub.ai_insight.max_grade == Decimal("10.0")
    assert mock_sub.ai_insight.reasoning == "Excelente"
    mock_session.commit.assert_awaited_once()


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

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
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
        await service.process_submission_ai_task(sub_id)

    assert mock_sub.status == SubmissionStatus.AWAITING_REVIEW
    assert mock_sub.ai_insight.status == "failed"
    assert "Gemini API rate limit exceeded" in mock_sub.ai_insight.error_message
    mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_assignment_idempotency_when_draft_code_identical_should_not_enqueue_ai():
    from app.models.assignment import Assignment
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
    from app.models.assignment import Assignment
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
async def test_list_submissions_returns_all_and_filtered(
    db_session: AsyncSession,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Lista sem filtro
    all_subs = await submission_query_service.list_submissions(
        assignment_id=assignment_without_submissions.id,
        status_filter=None,
        db=db_session,
    )
    assert len(all_subs) >= 1
    assert any(s.id == submission_awaiting_review.id for s in all_subs)

    # Filtra por status awaiting_review
    filtered_awaiting = await submission_query_service.list_submissions(
        assignment_id=assignment_without_submissions.id,
        status_filter=SubmissionStatus.AWAITING_REVIEW,
        db=db_session,
    )
    assert len(filtered_awaiting) >= 1
    assert all(s.status == SubmissionStatus.AWAITING_REVIEW for s in filtered_awaiting)

    # Filtra por status published (não deve achar a submissão awaiting_review)
    filtered_published = await submission_query_service.list_submissions(
        assignment_id=assignment_without_submissions.id,
        status_filter=SubmissionStatus.PUBLISHED,
        db=db_session,
    )
    assert not any(s.id == submission_awaiting_review.id for s in filtered_published)


@pytest.mark.asyncio
async def test_evaluate_submission_when_publish_true_should_publish_and_set_grade(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    req = SubmissionEvaluationRequest(
        grade=Decimal("9.50"),
        general_feedback="Excelente código!",
        detailed_scores={"item": "ok"},
        publish=True,
    )

    evaluation = await submission_evaluation_service.evaluate_submission(
        submission=submission_awaiting_review,
        request=req,
        db=db_session,
    )

    assert evaluation.grade == Decimal("9.50")
    assert evaluation.general_feedback == "Excelente código!"
    assert submission_awaiting_review.status == SubmissionStatus.PUBLISHED
    assert submission_awaiting_review.grade == Decimal("9.50")


@pytest.mark.asyncio
async def test_evaluate_submission_when_publish_false_should_retain_grade_in_awaiting_review(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    req = SubmissionEvaluationRequest(
        grade=Decimal("8.00"),
        general_feedback="Rascunho de avaliação docente",
        publish=False,
    )

    evaluation = await submission_evaluation_service.evaluate_submission(
        submission=submission_awaiting_review,
        request=req,
        db=db_session,
    )

    assert evaluation.grade == Decimal("8.00")
    assert submission_awaiting_review.status == SubmissionStatus.AWAITING_REVIEW
    assert submission_awaiting_review.grade is None


@pytest.mark.asyncio
async def test_evaluate_submission_when_draft_should_raise_bad_request(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    submission_awaiting_review.status = SubmissionStatus.DRAFT
    await db_session.commit()

    req = SubmissionEvaluationRequest(grade=Decimal("10.00"))
    with pytest.raises(BadRequestException, match="rascunho"):
        await submission_evaluation_service.evaluate_submission(
            submission=submission_awaiting_review,
            request=req,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_evaluate_submission_when_pending_should_raise_bad_request(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    submission_awaiting_review.status = SubmissionStatus.PENDING
    await db_session.commit()

    req = SubmissionEvaluationRequest(grade=Decimal("10.00"))
    with pytest.raises(BadRequestException, match="processamento inicial"):
        await submission_evaluation_service.evaluate_submission(
            submission=submission_awaiting_review,
            request=req,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_get_submission_evaluation_when_not_published_and_student_should_raise_forbidden(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
    tenant: TenantContext,
):
    # Avaliação registrada pelo professor mas com publish=False
    req = SubmissionEvaluationRequest(grade=Decimal("7.00"), publish=False)
    await submission_evaluation_service.evaluate_submission(
        submission=submission_awaiting_review,
        request=req,
        db=db_session,
    )

    # Professor ou admin pode ver
    eval_teacher = await submission_evaluation_service.get_submission_evaluation(
        submission=submission_awaiting_review,
        is_teacher_or_admin=True,
        is_author=False,
        db=db_session,
    )
    assert eval_teacher.grade == Decimal("7.00")

    # Aluno autor tentando ver antes de publicada deve receber Forbidden
    with pytest.raises(ForbiddenException, match="publicada"):
        await submission_evaluation_service.get_submission_evaluation(
            submission=submission_awaiting_review,
            is_teacher_or_admin=False,
            is_author=True,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_get_submission_evaluation_when_published_student_can_view(
    db_session: AsyncSession,
    submission_published: Submission,
):
    eval_student = await submission_evaluation_service.get_submission_evaluation(
        submission=submission_published,
        is_teacher_or_admin=False,
        is_author=True,
        db=db_session,
    )
    assert eval_student.grade == Decimal("9.00")


@pytest.mark.asyncio
async def test_get_submission_evaluation_when_not_found_should_raise_not_found(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # Sem avaliação registrada
    with pytest.raises(NotFoundException, match="não encontrada"):
        await submission_evaluation_service.get_submission_evaluation(
            submission=submission_awaiting_review,
            is_teacher_or_admin=True,
            is_author=False,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_get_submission_detail_when_teacher_should_include_ai_insight_and_evaluation(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    detail = submission_query_service.get_submission_detail(
        submission=submission_awaiting_review,
        is_student=False,
    )
    assert detail.id == submission_awaiting_review.id
    assert detail.student.id == submission_awaiting_review.student_id
    assert not hasattr(detail, "student_id")
    assert not hasattr(detail, "assignment_id")
    assert detail.assignment.id == submission_awaiting_review.assignment_id
    assert detail.ai_insight is not None
    assert detail.ai_insight.status == "completed"


@pytest.mark.asyncio
async def test_get_submission_detail_when_student_and_not_published_should_mask_ai_insight_and_evaluation(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    detail = submission_query_service.get_submission_detail(
        submission=submission_awaiting_review,
        is_student=True,
    )
    assert detail.id == submission_awaiting_review.id
    assert not hasattr(detail, "ai_insight")
    assert detail.evaluation is None


@pytest.mark.asyncio
async def test_get_submission_detail_when_student_and_published_should_include_evaluation(
    db_session: AsyncSession,
    submission_published: Submission,
):
    detail = submission_query_service.get_submission_detail(
        submission=submission_published,
        is_student=True,
    )
    assert detail.id == submission_published.id
    assert not hasattr(detail, "ai_insight")
    assert detail.evaluation is not None
    assert detail.evaluation.grade == Decimal("9.00")


@pytest.mark.asyncio
async def test_list_submissions_filtering_by_student_id(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # Lista com student_id correspondente
    subs = await submission_query_service.list_submissions(
        assignment_id=submission_awaiting_review.assignment_id,
        status_filter=None,
        student_id=submission_awaiting_review.student_id,
        db=db_session,
    )
    assert len(subs) == 1
    assert subs[0].id == submission_awaiting_review.id

    # Lista com student_id aleatório/inexistente
    subs_empty = await submission_query_service.list_submissions(
        assignment_id=submission_awaiting_review.assignment_id,
        status_filter=None,
        student_id=uuid.uuid4(),
        db=db_session,
    )
    assert len(subs_empty) == 0


@pytest.mark.asyncio
async def test_publish_assignment_evaluations_when_submissions_have_evaluations_should_publish(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # Avalia a submissão mantendo em rascunho (publish=False)
    eval_req = SubmissionEvaluationRequest(grade=Decimal("8.50"), publish=False)
    await submission_evaluation_service.evaluate_submission(
        submission=submission_awaiting_review,
        request=eval_req,
        db=db_session,
    )
    assert submission_awaiting_review.status == SubmissionStatus.AWAITING_REVIEW
    assert submission_awaiting_review.grade is None

    # Dispara a publicação em lote
    count = await submission_evaluation_service.publish_assignment_evaluations(
        assignment_id=submission_awaiting_review.assignment_id,
        db=db_session,
    )
    assert count == 1

    await db_session.refresh(submission_awaiting_review)
    assert submission_awaiting_review.status == SubmissionStatus.PUBLISHED
    assert submission_awaiting_review.grade == Decimal("8.50")


@pytest.mark.asyncio
async def test_publish_assignment_evaluations_when_no_evaluation_exists_should_skip(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # submission_awaiting_review não possui avaliação docente associada
    count = await submission_evaluation_service.publish_assignment_evaluations(
        assignment_id=submission_awaiting_review.assignment_id,
        db=db_session,
    )
    assert count == 0

    await db_session.refresh(submission_awaiting_review)
    assert submission_awaiting_review.status == SubmissionStatus.AWAITING_REVIEW
    assert submission_awaiting_review.grade is None


@pytest.mark.asyncio
async def test_publish_assignment_evaluations_with_selective_submission_ids(
    db_session: AsyncSession,
    assignment_without_submissions: Assignment,
    enrolled_student: ClassroomStudent,
    create_submission: Callable[..., Awaitable[Submission]],
):
    # Cria segundo estudante válido no banco
    other_student = User(
        id=uuid.uuid4(),
        email=f"other_{uuid.uuid4().hex[:6]}@test.com",
        full_name="Other Student",
    )
    db_session.add(other_student)
    await db_session.commit()

    # Cria duas submissões
    sub1 = await create_submission(
        assignment=assignment_without_submissions,
        student_id=enrolled_student.student_id,
        status=SubmissionStatus.AWAITING_REVIEW,
        content={"language": "python3", "code": "pass"},
        evaluation_grade=Decimal("7.00"),
        evaluation_feedback="Bom",
    )
    sub1.status = SubmissionStatus.AWAITING_REVIEW
    sub1.grade = None

    sub2 = await create_submission(
        assignment=assignment_without_submissions,
        student_id=other_student.id,
        status=SubmissionStatus.AWAITING_REVIEW,
        content={"language": "python3", "code": "pass"},
        evaluation_grade=Decimal("9.00"),
        evaluation_feedback="Excelente",
    )
    sub2.status = SubmissionStatus.AWAITING_REVIEW
    sub2.grade = None
    await db_session.commit()

    # Publica seletivamente apenas sub1
    count = await submission_evaluation_service.publish_assignment_evaluations(
        assignment_id=assignment_without_submissions.id,
        db=db_session,
        submission_ids=[sub1.id],
    )
    assert count == 1

    await db_session.refresh(sub1)
    await db_session.refresh(sub2)
    assert sub1.status == SubmissionStatus.PUBLISHED
    assert sub1.grade == Decimal("7.00")
    assert sub2.status == SubmissionStatus.AWAITING_REVIEW
    assert sub2.grade is None


@pytest.mark.asyncio
async def test_list_submissions_with_search_query(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # Busca por parte do email ou nome do aluno da submissão
    student = submission_awaiting_review.student
    subs = await submission_query_service.list_submissions(
        assignment_id=submission_awaiting_review.assignment_id,
        status_filter=None,
        db=db_session,
        search_query=student.email[:5],
    )
    assert len(subs) == 1
    assert subs[0].id == submission_awaiting_review.id

    # Busca com termo que não existe
    subs_empty = await submission_query_service.list_submissions(
        assignment_id=submission_awaiting_review.assignment_id,
        status_filter=None,
        db=db_session,
        search_query="termo_totalmente_inexistente_xyz",
    )
    assert len(subs_empty) == 0


@pytest.mark.asyncio
async def test_get_assignment_submission_stats(
    db_session: AsyncSession,
    assignment_without_submissions: Assignment,
    enrolled_student: ClassroomStudent,
    create_submission: Callable[..., Awaitable[Submission]],
):
    # Cria outros 2 estudantes válidos no banco
    u2 = User(
        id=uuid.uuid4(),
        email=f"u2_{uuid.uuid4().hex[:6]}@test.com",
        full_name="User Two",
    )
    u3 = User(
        id=uuid.uuid4(),
        email=f"u3_{uuid.uuid4().hex[:6]}@test.com",
        full_name="User Three",
    )
    db_session.add_all([u2, u3])
    await db_session.commit()

    # 1. Submissão 1: PENDING
    await create_submission(
        assignment=assignment_without_submissions,
        student_id=enrolled_student.student_id,
        status=SubmissionStatus.PENDING,
        content={"language": "python3", "code": "pass"},
    )

    # 2. Submissão 2: AWAITING_REVIEW pronta para liberar (com evaluation)
    sub2 = await create_submission(
        assignment=assignment_without_submissions,
        student_id=u2.id,
        status=SubmissionStatus.AWAITING_REVIEW,
        content={"language": "python3", "code": "pass"},
        evaluation_grade=Decimal("9.00"),
    )
    sub2.status = SubmissionStatus.AWAITING_REVIEW
    sub2.grade = None

    # 3. Submissão 3: PUBLISHED com nota 8.00
    await create_submission(
        assignment=assignment_without_submissions,
        student_id=u3.id,
        status=SubmissionStatus.PUBLISHED,
        content={"language": "python3", "code": "pass"},
        grade=Decimal("8.00"),
        evaluation_grade=Decimal("8.00"),
    )
    await db_session.commit()

    stats = await submission_query_service.get_assignment_submission_stats(
        assignment=assignment_without_submissions,
        db=db_session,
    )
    assert stats.assignment_id == assignment_without_submissions.id
    assert stats.total_submissions == 3
    assert stats.pending == 1
    assert stats.ready_to_publish == 1
    assert stats.published == 1
    assert stats.average_grade == Decimal("8.00")


@pytest.mark.asyncio
async def test_list_submissions_with_classroom_and_org_filters(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
    assignment_with_submissions: Assignment,
):
    # Filtro por classroom_id e organization_id correspondente
    subs = await submission_query_service.list_submissions(
        db=db_session,
        classroom_id=assignment_with_submissions.classroom_id,
        organization_id=assignment_with_submissions.classroom.organization_id,
    )
    assert len(subs) >= 1
    assert any(s.id == submission_awaiting_review.id for s in subs)
    assert all(
        s.assignment.classroom_id == assignment_with_submissions.classroom_id
        for s in subs
    )

    # Filtro por classroom_id aleatório/inexistente
    subs_empty = await submission_query_service.list_submissions(
        db=db_session,
        classroom_id=uuid.uuid4(),
    )
    assert len(subs_empty) == 0

    # Filtro por organization_id aleatório/inexistente
    subs_wrong_org = await submission_query_service.list_submissions(
        db=db_session,
        organization_id=uuid.uuid4(),
    )
    assert len(subs_wrong_org) == 0


@pytest.mark.asyncio
async def test_list_submissions_with_teacher_and_enrolled_student_filters(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
    assignment_with_submissions: Assignment,
):
    teacher_id = assignment_with_submissions.classroom.teacher_id
    student_id = submission_awaiting_review.student_id

    # Filtro por teacher_id correto
    subs_teacher = await submission_query_service.list_submissions(
        db=db_session,
        teacher_id=teacher_id,
    )
    assert len(subs_teacher) >= 1
    assert any(s.id == submission_awaiting_review.id for s in subs_teacher)

    # Filtro por enrolled_student_id
    subs_student = await submission_query_service.list_submissions(
        db=db_session,
        enrolled_student_id=student_id,
        student_id=student_id,
    )
    assert len(subs_student) >= 1
    assert all(s.student_id == student_id for s in subs_student)

    # Filtro por enrolled_student_id inexistente
    subs_none = await submission_query_service.list_submissions(
        db=db_session,
        enrolled_student_id=uuid.uuid4(),
    )
    assert len(subs_none) == 0


@pytest.mark.asyncio
async def test_list_submissions_without_db_raises_value_error():
    with pytest.raises(ValueError, match="Database session is required"):
        await submission_query_service.list_submissions(db=None)


@pytest.mark.asyncio
async def test_get_submission_detail_includes_assignment_info(
    submission_awaiting_review: Submission,
):
    detail = submission_query_service.get_submission_detail(
        submission=submission_awaiting_review,
        is_student=False,
    )
    assert detail.assignment is not None
    assert detail.assignment.id == submission_awaiting_review.assignment_id
    assert detail.assignment.title == submission_awaiting_review.assignment.title
    assert (
        detail.assignment.classroom_id
        == submission_awaiting_review.assignment.classroom_id
    )


# --- Testes de Auto-save / Rascunhos (save_draft_submission) ---


@pytest.mark.asyncio
async def test_save_draft_submission_when_new_should_create_draft(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    request = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3", code="def partial_code():\n    pass\n"
        )
    )

    sub = await submission_lifecycle_service.save_draft_submission(
        assignment=assignment_without_submissions,
        student_id=tenant.student.user.id,
        request=request,
        db=db_session,
    )

    assert sub.id is not None
    assert sub.status == SubmissionStatus.DRAFT
    assert sub.content["code"] == "def partial_code():\n    pass\n"
    assert sub.grade is None


@pytest.mark.asyncio
async def test_save_draft_submission_when_draft_already_exists_should_update(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Primeiro rascunho
    req1 = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(language="python3", code="pass")
    )
    sub1 = await submission_lifecycle_service.save_draft_submission(
        assignment=assignment_without_submissions,
        student_id=tenant.student.user.id,
        request=req1,
        db=db_session,
    )

    # Atualização do rascunho
    req2 = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3", code="def updated(): return 42"
        )
    )
    sub2 = await submission_lifecycle_service.save_draft_submission(
        assignment=assignment_without_submissions,
        student_id=tenant.student.user.id,
        request=req2,
        db=db_session,
    )

    assert sub2.id == sub1.id
    assert sub2.status == SubmissionStatus.DRAFT
    assert sub2.content["code"] == "def updated(): return 42"


@pytest.mark.asyncio
async def test_save_draft_submission_when_already_submitted_pending_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Cria submissão formal em PENDING
    sub = Submission(
        assignment_id=assignment_without_submissions.id,
        student_id=tenant.student.user.id,
        content={"language": "python3", "code": "def f(): pass"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(sub)
    await db_session.commit()

    req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(language="python3", code="novo")
    )
    with pytest.raises(BadRequestException) as exc_info:
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=req,
            db=db_session,
        )
    assert "desfaça a entrega primeiro" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_draft_submission_when_already_published_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    sub = Submission(
        assignment_id=assignment_without_submissions.id,
        student_id=tenant.student.user.id,
        content={"language": "python3", "code": "def f(): pass"},
        status=SubmissionStatus.PUBLISHED,
        grade=Decimal("10.00"),
    )
    db_session.add(sub)
    await db_session.commit()

    req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(language="python3", code="novo")
    )
    with pytest.raises(BadRequestException) as exc_info:
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=req,
            db=db_session,
        )
    assert "já foi corrigida e avaliada" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_draft_submission_when_deadline_expired_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Define prazo no passado
    assignment_without_submissions.deadline = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(language="python3", code="pass")
    )
    with pytest.raises(BadRequestException) as exc_info:
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=req,
            db=db_session,
        )
    assert "prazo para esta atividade já expirou" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_draft_submission_when_type_mismatch_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Atividade é do tipo CODE, mas enviou respostas de questionário
    req = SubmissionDraftRequest(
        content=QuestionnaireSubmissionDraftContent(answers=[])
    )
    with pytest.raises(BadRequestException) as exc_info:
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=req,
            db=db_session,
        )
    assert "esperado rascunho de código" in str(exc_info.value)


@pytest.mark.asyncio
async def test_save_draft_submission_when_disallowed_language_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(language="ruby", code="puts 1")
    )
    with pytest.raises(BadRequestException) as exc_info:
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=req,
            db=db_session,
        )
    assert "não é permitida para esta atividade" in str(exc_info.value)


# --- Testes de Reprocessamento de IA (retry_ai_evaluation) ---


@pytest.mark.asyncio
async def test_retry_ai_evaluation_when_published_should_raise_bad_request(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    submission_awaiting_review.status = SubmissionStatus.PUBLISHED
    await db_session.commit()

    bg_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await submission_ai_worker.retry_ai_evaluation(
            submission=submission_awaiting_review,
            db=db_session,
            background_tasks=bg_tasks,
        )
    assert "Não é possível reprocessar IA para submissões já avaliadas" in str(
        exc_info.value
    )


@pytest.mark.asyncio
async def test_retry_ai_evaluation_when_draft_should_raise_bad_request(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    submission_awaiting_review.status = SubmissionStatus.DRAFT
    await db_session.commit()

    bg_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await submission_ai_worker.retry_ai_evaluation(
            submission=submission_awaiting_review,
            db=db_session,
            background_tasks=bg_tasks,
        )
    assert "estado de rascunho" in str(exc_info.value)


@pytest.mark.asyncio
async def test_retry_ai_evaluation_when_objective_questionnaire_should_raise_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    objective_questionnaire_on_review: Assignment,
):
    # Submissão de questionário 100% objetivo
    sub = Submission(
        assignment_id=objective_questionnaire_on_review.id,
        student_id=tenant.student.user.id,
        content={"answers": [{"question_id": 1, "selected_option_id": "a"}]},
        status=SubmissionStatus.AWAITING_REVIEW,
    )
    sub.assignment = objective_questionnaire_on_review
    db_session.add(sub)
    await db_session.commit()

    bg_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await submission_ai_worker.retry_ai_evaluation(
            submission=sub,
            db=db_session,
            background_tasks=bg_tasks,
        )
    assert "não requer análise de IA" in str(exc_info.value)


@pytest.mark.asyncio
async def test_retry_ai_evaluation_success_schedules_task(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    # Simula insight anterior com falha
    if not submission_awaiting_review.ai_insight:
        submission_awaiting_review.ai_insight = SubmissionAiInsight(
            submission_id=submission_awaiting_review.id,
            status="failed",
            error_message="Timeout",
        )
        db_session.add(submission_awaiting_review.ai_insight)
    else:
        submission_awaiting_review.ai_insight.status = "failed"
        submission_awaiting_review.ai_insight.error_message = "Timeout"
    await db_session.commit()

    bg_tasks = BackgroundTasks()
    sub = await submission_ai_worker.retry_ai_evaluation(
        submission=submission_awaiting_review,
        db=db_session,
        background_tasks=bg_tasks,
    )

    assert sub.status == SubmissionStatus.PENDING
    assert sub.ai_insight.status == "in_progress"
    assert sub.ai_insight.error_message is None
    # Verifica que a tarefa foi adicionada às BackgroundTasks
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_retry_ai_evaluation_when_already_pending_should_raise_bad_request(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    submission_awaiting_review.status = SubmissionStatus.PENDING
    await db_session.commit()

    bg_tasks = BackgroundTasks()
    with pytest.raises(BadRequestException) as exc_info:
        await submission_ai_worker.retry_ai_evaluation(
            submission=submission_awaiting_review,
            db=db_session,
            background_tasks=bg_tasks,
        )
    assert "já se encontra em processamento de IA" in str(exc_info.value)


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


@pytest.mark.asyncio
async def test_retry_ai_evaluation_when_insight_is_none_creates_new_insight(
    db_session: AsyncSession,
    submission_awaiting_review: Submission,
):
    if submission_awaiting_review.ai_insight:
        await db_session.delete(submission_awaiting_review.ai_insight)
        submission_awaiting_review.ai_insight = None
        await db_session.commit()

    bg_tasks = BackgroundTasks()
    sub = await submission_ai_worker.retry_ai_evaluation(
        submission=submission_awaiting_review,
        db=db_session,
        background_tasks=bg_tasks,
    )

    assert sub.status == SubmissionStatus.PENDING
    assert sub.ai_insight is not None
    assert sub.ai_insight.status == "in_progress"
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_save_draft_submission_concurrent_race_integrity_error_recovery(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    draft_req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3",
            code="x = 10",
        )
    )

    existing_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=assignment_without_submissions.id,
        student_id=tenant.student.user.id,
        content={"language": "python3", "code": "x = 5"},
        status=SubmissionStatus.DRAFT,
    )
    db_session.add(existing_sub)
    await db_session.commit()

    with patch.object(
        db_session,
        "commit",
        side_effect=[IntegrityError("conflict", orig=MagicMock(), params={}), None],
    ):
        sub = await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=draft_req,
            db=db_session,
        )
        assert sub.status == SubmissionStatus.DRAFT


@pytest.mark.asyncio
async def test_save_draft_submission_concurrent_race_when_published_raises_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    existing_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=assignment_without_submissions.id,
        student_id=tenant.student.user.id,
        content={"language": "python3", "code": "x = 5"},
        status=SubmissionStatus.PUBLISHED,
    )
    db_session.add(existing_sub)
    await db_session.commit()

    draft_req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3",
            code="x = 10",
        )
    )

    with (
        patch.object(
            db_session,
            "commit",
            side_effect=IntegrityError("conflict", orig=MagicMock(), params={}),
        ),
        pytest.raises(BadRequestException, match="já foi corrigida e avaliada"),
    ):
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=draft_req,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_save_draft_submission_concurrent_race_when_pending_raises_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    existing_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=assignment_without_submissions.id,
        student_id=tenant.student.user.id,
        content={"language": "python3", "code": "x = 5"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(existing_sub)
    await db_session.commit()

    draft_req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3",
            code="x = 10",
        )
    )

    with (
        patch.object(
            db_session,
            "commit",
            side_effect=IntegrityError("conflict", orig=MagicMock(), params={}),
        ),
        pytest.raises(BadRequestException, match="já foi submetida formalmente"),
    ):
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_without_submissions,
            student_id=tenant.student.user.id,
            request=draft_req,
            db=db_session,
        )


@pytest.mark.asyncio
async def test_save_draft_submission_questionnaire_with_code_content_raises_bad_request(
    db_session: AsyncSession,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
):
    # assignment_with_submissions é do tipo QUESTIONNAIRE
    draft_req = SubmissionDraftRequest(
        content=CodeSubmissionDraftContent(
            language="python3",
            code="x = 10",
        )
    )
    with pytest.raises(
        BadRequestException, match="esperado rascunho de respostas de questionário"
    ):
        await submission_lifecycle_service.save_draft_submission(
            assignment=assignment_with_submissions,
            student_id=tenant.student.user.id,
            request=draft_req,
            db=db_session,
        )
