from decimal import Decimal

from pydantic import BaseModel

from app.domain.grading.questionnaire_grader import (
    QuestionnaireGrader,
    QuestionnaireGradingResult,
)


def test_grade_objective_when_all_correct() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 5.0, "correct_option_id": "b"},
        {"id": 2, "type": "choice", "points": 5.0, "correct_option_id": "a"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "b"},
        {"question_id": 2, "selected_option_id": "a"},
    ]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    assert isinstance(result, QuestionnaireGradingResult)
    assert result.total_points == Decimal("10.00")
    assert len(result.questions_evaluation) == 2

    assert result.questions_evaluation[0].question_id == 1
    assert result.questions_evaluation[0].awarded_points == 5.0
    assert result.questions_evaluation[0].max_points == 5.0
    assert result.questions_evaluation[0].is_correct is True

    assert result.questions_evaluation[1].question_id == 2
    assert result.questions_evaluation[1].awarded_points == 5.0
    assert result.questions_evaluation[1].max_points == 5.0
    assert result.questions_evaluation[1].is_correct is True


def test_grade_objective_when_all_incorrect() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 4.0, "correct_option_id": "c"},
        {"id": 2, "type": "choice", "points": 6.0, "correct_option_id": "d"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "a"},  # Errada
        {"question_id": 2, "selected_option_id": "b"},  # Errada
    ]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    assert result.total_points == Decimal("0.00")
    assert len(result.questions_evaluation) == 2
    assert result.questions_evaluation[0].awarded_points == 0.0
    assert result.questions_evaluation[0].is_correct is False
    assert result.questions_evaluation[1].awarded_points == 0.0
    assert result.questions_evaluation[1].is_correct is False


def test_grade_objective_when_partial_correct() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 2.5, "correct_option_id": "opt1"},
        {"id": 2, "type": "choice", "points": 3.5, "correct_option_id": "opt2"},
        {"id": 3, "type": "choice", "points": 4.0, "correct_option_id": "opt3"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "opt1"},  # Correta (+2.5)
        {"question_id": 2, "selected_option_id": "wrong"},  # Errada (+0.0)
        {"question_id": 3, "selected_option_id": "opt3"},  # Correta (+4.0)
    ]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    assert result.total_points == Decimal("6.50")
    assert len(result.questions_evaluation) == 3
    assert result.questions_evaluation[0].is_correct is True
    assert result.questions_evaluation[0].awarded_points == 2.5
    assert result.questions_evaluation[1].is_correct is False
    assert result.questions_evaluation[1].awarded_points == 0.0
    assert result.questions_evaluation[2].is_correct is True
    assert result.questions_evaluation[2].awarded_points == 4.0


def test_grade_objective_when_unanswered_or_omitted() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 3.0, "correct_option_id": "a"},
        {"id": 2, "type": "choice", "points": 4.0, "correct_option_id": "b"},
        {"id": 3, "type": "choice", "points": 3.0, "correct_option_id": "c"},
    ]
    # Apenas questão 1 respondida
    answers = [{"question_id": 1, "selected_option_id": "a"}]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    assert result.total_points == Decimal("3.00")
    assert len(result.questions_evaluation) == 3
    assert result.questions_evaluation[0].is_correct is True
    assert result.questions_evaluation[0].awarded_points == 3.0
    assert result.questions_evaluation[1].is_correct is False
    assert result.questions_evaluation[1].awarded_points == 0.0
    assert result.questions_evaluation[2].is_correct is False
    assert result.questions_evaluation[2].awarded_points == 0.0


def test_grade_objective_when_answers_empty() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 5.0, "correct_option_id": "a"},
        {"id": 2, "type": "choice", "points": 5.0, "correct_option_id": "b"},
    ]
    result = QuestionnaireGrader.grade_objective(questions, [])

    assert result.total_points == Decimal("0.00")
    assert len(result.questions_evaluation) == 2
    assert all(item.is_correct is False for item in result.questions_evaluation)
    assert all(item.awarded_points == 0.0 for item in result.questions_evaluation)


def test_grade_objective_when_questions_empty() -> None:
    answers = [{"question_id": 1, "selected_option_id": "a"}]
    result = QuestionnaireGrader.grade_objective([], answers)

    assert result.total_points == Decimal("0.00")
    assert result.questions_evaluation == []
    assert result.detailed_scores == {"questions_evaluation": []}


def test_grade_objective_ignores_open_questions() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 4.0, "correct_option_id": "b"},
        {
            "id": 2,
            "type": "open",
            "points": 6.0,
            "statement": "Explique o Teorema CAP.",
        },
        {"id": 3, "type": "choice", "points": 2.0, "correct_option_id": "c"},
    ]
    answers = [
        {"question_id": 1, "selected_option_id": "b"},
        {"question_id": 2, "text_answer": "Consistência, Disponibilidade..."},
        {"question_id": 3, "selected_option_id": "c"},
    ]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    # Apenas as questões objetivas (1 e 3) devem ser avaliadas
    assert result.total_points == Decimal("6.00")
    assert len(result.questions_evaluation) == 2
    assert result.questions_evaluation[0].question_id == 1
    assert result.questions_evaluation[0].awarded_points == 4.0
    assert result.questions_evaluation[1].question_id == 3
    assert result.questions_evaluation[1].awarded_points == 2.0


def test_grade_objective_with_pydantic_models() -> None:
    class DummyChoiceQuestion(BaseModel):
        id: int
        type: str = "choice"
        points: float
        correct_option_id: str

    class DummyChoiceAnswer(BaseModel):
        question_id: int
        selected_option_id: str

    questions = [
        DummyChoiceQuestion(id=1, points=5.0, correct_option_id="x"),
        DummyChoiceQuestion(id=2, points=5.0, correct_option_id="y"),
    ]
    answers = [
        DummyChoiceAnswer(question_id=1, selected_option_id="x"),
        DummyChoiceAnswer(question_id=2, selected_option_id="z"),
    ]

    result = QuestionnaireGrader.grade_objective(questions, answers)  # type: ignore[arg-type]

    assert result.total_points == Decimal("5.00")
    assert len(result.questions_evaluation) == 2
    assert result.questions_evaluation[0].is_correct is True
    assert result.questions_evaluation[1].is_correct is False


def test_questionnaire_grading_result_unpacking_and_detailed_scores() -> None:
    questions = [
        {"id": 1, "type": "choice", "points": 10.0, "correct_option_id": "yes"}
    ]
    answers = [{"question_id": 1, "selected_option_id": "yes"}]

    result = QuestionnaireGrader.grade_objective(questions, answers)

    # Valida método as_tuple() e propriedade detailed_scores
    grade, detailed = result.as_tuple()
    assert grade == Decimal("10.00")
    assert detailed == {
        "questions_evaluation": [
            {
                "question_id": 1,
                "type": "choice",
                "awarded_points": 10.0,
                "max_points": 10.0,
                "is_correct": True,
            }
        ]
    }
    assert result.detailed_scores == detailed
