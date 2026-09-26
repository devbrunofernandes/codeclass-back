from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from app.services.submission_service import SubmissionService


def test_grade_objective_questionnaire_when_all_correct():
    service = SubmissionService()
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
    service = SubmissionService()
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
    service = SubmissionService()
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
    service = SubmissionService()
    allowed_langs = ["python3", "javascript"]

    with pytest.raises(BadRequestException):
        service.validate_code_content("c++", "int main() {}", allowed_langs)


def test_validate_code_submission_language_when_valid_should_pass():
    service = SubmissionService()
    allowed_langs = ["python3", "javascript"]

    # Não deve levantar exceção
    service.validate_code_content("python3", "print(1)", allowed_langs)
