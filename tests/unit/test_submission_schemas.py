import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.enums import SubmissionStatus
from app.schemas.submission import (
    ChoiceAnswerContent,
    ChoiceAnswerDraftContent,
    CodeSubmissionContent,
    CodeSubmissionDraftContent,
    OpenAnswerContent,
    OpenAnswerDraftContent,
    QuestionnaireSubmissionContent,
    QuestionnaireSubmissionDraftContent,
    SubmissionCreateRequest,
    SubmissionDraftRequest,
    SubmissionStudentResponse,
)


def test_code_submission_content_when_valid_should_instantiate():
    content = CodeSubmissionContent(
        language="python3",
        code="def solve(a, b):\n    return a + b\n",
    )
    assert content.language == "python3"
    assert "return a + b" in content.code


def test_code_submission_content_when_empty_should_fail():
    with pytest.raises(ValidationError):
        CodeSubmissionContent(language="", code="")


def test_choice_answer_content_when_valid_should_instantiate():
    answer = ChoiceAnswerContent(question_id=1, selected_option_id="b")
    assert answer.question_id == 1
    assert answer.selected_option_id == "b"


def test_choice_answer_content_when_invalid_should_fail():
    with pytest.raises(ValidationError):
        ChoiceAnswerContent(question_id=0, selected_option_id="")


def test_open_answer_content_when_valid_should_instantiate():
    answer = OpenAnswerContent(
        question_id=2, text_answer="Lista encadeada em cada bucket."
    )
    assert answer.question_id == 2
    assert "Lista encadeada" in answer.text_answer


def test_open_answer_content_when_empty_should_fail():
    with pytest.raises(ValidationError):
        OpenAnswerContent(question_id=2, text_answer="")


def test_questionnaire_submission_content_when_valid_should_instantiate():
    content = QuestionnaireSubmissionContent(
        answers=[
            ChoiceAnswerContent(question_id=1, selected_option_id="a"),
            OpenAnswerContent(question_id=2, text_answer="Explicação teórica"),
        ]
    )
    assert len(content.answers) == 2


def test_questionnaire_submission_content_when_empty_answers_should_fail():
    with pytest.raises(ValidationError):
        QuestionnaireSubmissionContent(answers=[])


def test_questionnaire_submission_content_when_duplicate_question_ids_should_fail():
    with pytest.raises(ValidationError) as exc_info:
        QuestionnaireSubmissionContent(
            answers=[
                ChoiceAnswerContent(question_id=1, selected_option_id="a"),
                ChoiceAnswerContent(question_id=1, selected_option_id="b"),
            ]
        )
    assert "mais de uma vez" in str(exc_info.value)


def test_submission_create_request_polymorphic_instantiation():
    req_code = SubmissionCreateRequest(
        content=CodeSubmissionContent(language="python3", code="print(1)")
    )
    assert isinstance(req_code.content, CodeSubmissionContent)

    req_quest = SubmissionCreateRequest(
        content=QuestionnaireSubmissionContent(
            answers=[ChoiceAnswerContent(question_id=1, selected_option_id="c")]
        )
    )
    assert isinstance(req_quest.content, QuestionnaireSubmissionContent)


def test_submission_student_response_should_not_have_ai_insights_field():
    sub_id = uuid.uuid4()
    assignment_id = uuid.uuid4()
    student_id = uuid.uuid4()
    now = datetime.now(UTC)

    resp = SubmissionStudentResponse(
        id=sub_id,
        assignment_id=assignment_id,
        student_id=student_id,
        content={"language": "python3", "code": "pass"},
        grade=Decimal("10.00"),
        status=SubmissionStatus.PUBLISHED,
        submitted_at=now,
    )

    assert resp.id == sub_id
    assert resp.status == SubmissionStatus.PUBLISHED
    # Garantia estrita: campo ai_insights não existe no schema do estudante
    assert "ai_insights" not in resp.model_dump()
    assert "ai_insight" not in resp.model_dump()


def test_code_submission_draft_content_when_empty_should_be_valid():
    draft = CodeSubmissionDraftContent()
    assert draft.language == "python3"
    assert draft.code == ""


def test_choice_answer_draft_content_with_none_should_be_valid():
    ans = ChoiceAnswerDraftContent(question_id=1, selected_option_id=None)
    assert ans.question_id == 1
    assert ans.selected_option_id is None


def test_open_answer_draft_content_with_none_should_be_valid():
    ans = OpenAnswerDraftContent(question_id=2, text_answer=None)
    assert ans.question_id == 2
    assert ans.text_answer is None


def test_questionnaire_submission_draft_content_when_empty_should_be_valid():
    draft = QuestionnaireSubmissionDraftContent()
    assert draft.answers == []


def test_questionnaire_submission_draft_content_with_partial_answers():
    draft = QuestionnaireSubmissionDraftContent(
        answers=[
            ChoiceAnswerDraftContent(question_id=1, selected_option_id="b"),
            OpenAnswerDraftContent(question_id=2, text_answer=None),
        ]
    )
    assert len(draft.answers) == 2


def test_questionnaire_submission_draft_content_duplicate_ids_should_fail():
    with pytest.raises(ValidationError) as exc_info:
        QuestionnaireSubmissionDraftContent(
            answers=[
                ChoiceAnswerDraftContent(question_id=1, selected_option_id="a"),
                ChoiceAnswerDraftContent(question_id=1, selected_option_id="b"),
            ]
        )
    assert "mais de uma vez" in str(exc_info.value)


def test_submission_draft_request_polymorphic_instantiation():
    req_code = SubmissionDraftRequest(content=CodeSubmissionDraftContent(code="x = 1"))
    assert isinstance(req_code.content, CodeSubmissionDraftContent)

    req_quest = SubmissionDraftRequest(
        content=QuestionnaireSubmissionDraftContent(answers=[])
    )
    assert isinstance(req_quest.content, QuestionnaireSubmissionDraftContent)
