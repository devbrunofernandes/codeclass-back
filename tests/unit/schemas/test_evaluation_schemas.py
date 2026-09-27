import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.enums import AssignmentType, SubmissionStatus
from app.schemas.evaluation import (
    BatchEvaluationReleaseResponse,
    QuestionEvaluationItem,
    SubmissionEvaluationRequest,
    SubmissionEvaluationResponse,
)
from app.schemas.submission import (
    SubmissionAssignmentInfo,
    SubmissionDetailResponse,
    SubmissionStudentInfo,
    SubmissionSummaryResponse,
)


def test_question_evaluation_item_valid():
    item = QuestionEvaluationItem(
        question_id=1,
        type="choice",
        awarded_points=2.5,
        max_points=2.5,
        is_correct=True,
        teacher_feedback="Perfeito",
    )
    assert item.question_id == 1
    assert item.awarded_points == 2.5
    assert item.is_correct is True


def test_question_evaluation_item_invalid_points():
    with pytest.raises(ValidationError):
        QuestionEvaluationItem(
            question_id=0,  # ge=1
            type="choice",
            awarded_points=-1.0,
            max_points=2.0,
        )


def test_submission_evaluation_request_defaults():
    req = SubmissionEvaluationRequest(grade=Decimal("8.5"))
    assert req.grade == Decimal("8.5")
    assert req.publish is True
    assert req.general_feedback is None
    assert req.detailed_scores is None


def test_submission_evaluation_request_invalid_grades():
    with pytest.raises(ValidationError):
        SubmissionEvaluationRequest(grade=Decimal("-0.1"))

    with pytest.raises(ValidationError):
        SubmissionEvaluationRequest(grade=Decimal("100.1"))


def test_submission_evaluation_request_with_details():
    req = SubmissionEvaluationRequest(
        grade=Decimal("9.0"),
        general_feedback="Muito bom trabalho!",
        detailed_scores={
            "questions_evaluation": [
                {
                    "question_id": 1,
                    "awarded_points": 5.0,
                    "max_points": 5.0,
                }
            ]
        },
        publish=False,
    )
    assert req.grade == Decimal("9.0")
    assert req.publish is False
    assert req.general_feedback == "Muito bom trabalho!"
    assert req.detailed_scores is not None


def test_submission_evaluation_response_from_dict():
    eval_id = uuid.uuid4()
    sub_id = uuid.uuid4()
    now = datetime.now(UTC)
    resp = SubmissionEvaluationResponse(
        id=eval_id,
        submission_id=sub_id,
        grade=Decimal("10.00"),
        general_feedback="Excelente",
        detailed_scores={},
        evaluated_at=now,
        updated_at=now,
    )
    assert resp.id == eval_id
    assert resp.submission_id == sub_id
    assert resp.grade == Decimal("10.00")


def test_submission_summary_response_with_student_info():
    sub_id = uuid.uuid4()
    assign_id = uuid.uuid4()
    class_id = uuid.uuid4()
    student_id = uuid.uuid4()
    now = datetime.now(UTC)

    summary = SubmissionSummaryResponse(
        id=sub_id,
        assignment=SubmissionAssignmentInfo(
            id=assign_id,
            title="Tarefa de Algoritmos",
            type=AssignmentType.CODE,
            classroom_id=class_id,
        ),
        student=SubmissionStudentInfo(
            id=student_id,
            full_name="Grace Hopper",
            email="grace@example.com",
        ),
        grade=Decimal("9.50"),
        status=SubmissionStatus.PUBLISHED,
        submitted_at=now,
        ai_insight_status="completed",
    )
    assert summary.assignment.id == assign_id
    assert not hasattr(summary, "assignment_id")
    assert summary.student is not None
    assert summary.student.full_name == "Grace Hopper"
    assert summary.ai_insight_status == "completed"


def test_submission_detail_response():
    sub_id = uuid.uuid4()
    assign_id = uuid.uuid4()
    class_id = uuid.uuid4()
    student_id = uuid.uuid4()
    now = datetime.now(UTC)

    detail = SubmissionDetailResponse(
        id=sub_id,
        assignment=SubmissionAssignmentInfo(
            id=assign_id,
            title="Questionário de Grafos",
            type=AssignmentType.QUESTIONNAIRE,
            classroom_id=class_id,
        ),
        student=SubmissionStudentInfo(
            id=student_id,
            full_name="Ada Lovelace",
            email="ada@example.com",
        ),
        content={"language": "python3", "code": "print(1)"},
        grade=Decimal("10.00"),
        status=SubmissionStatus.PUBLISHED,
        submitted_at=now,
        ai_insight=None,
        evaluation=None,
    )
    assert detail.assignment.id == assign_id
    assert not hasattr(detail, "assignment_id")
    assert detail.content["language"] == "python3"
    assert detail.status == SubmissionStatus.PUBLISHED
    assert detail.student.id == student_id


def test_batch_evaluation_release_response():
    assign_id = uuid.uuid4()
    resp = BatchEvaluationReleaseResponse(
        assignment_id=assign_id,
        published_count=5,
        message="5 correções publicadas com sucesso.",
    )
    assert resp.assignment_id == assign_id
    assert resp.published_count == 5
    assert "5 correções" in resp.message
