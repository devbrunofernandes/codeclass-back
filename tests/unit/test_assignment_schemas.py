import pytest
from pydantic import ValidationError

from app.models.enums import AssignmentType, ReleasePolicyType
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentStudentResponse,
    ChoiceOptionConfig,
    ChoiceQuestionConfig,
    CodeAssignmentConfig,
    LanguageConfig,
    OpenQuestionConfig,
    QuestionnaireAssignmentConfig,
    TestCaseConfig,
)


def test_code_assignment_config_when_valid_should_instantiate():
    # Arrange & Act
    config = CodeAssignmentConfig(
        languages=[
            LanguageConfig(name="python3", starter_code="def solucao():\n    pass\n")
        ],
        time_limit_sec=2.0,
        memory_limit_mb=128,
        rubric="Verificar uso de recursão.",
        test_cases=[
            TestCaseConfig(id=1, input="1 2\n", expected_output="3\n"),
            TestCaseConfig(id=2, input="0 0\n", expected_output="0\n"),
        ],
    )

    # Assert
    assert len(config.languages) == 1
    assert config.languages[0].name == "python3"
    assert config.time_limit_sec == 2.0
    assert config.memory_limit_mb == 128
    assert len(config.test_cases) == 2


def test_code_assignment_config_when_languages_empty_should_fail():
    with pytest.raises(ValidationError):
        CodeAssignmentConfig(
            languages=[],
            test_cases=[],
        )


def test_questionnaire_assignment_config_when_valid_should_instantiate():
    # Arrange & Act
    config = QuestionnaireAssignmentConfig(
        questions=[
            ChoiceQuestionConfig(
                id=1,
                points=2.5,
                statement="Qual a complexidade do algoritmo?",
                options=[
                    ChoiceOptionConfig(id="a", text="O(1)"),
                    ChoiceOptionConfig(id="b", text="O(n)"),
                ],
                correct_option_id="b",
            ),
            OpenQuestionConfig(
                id=2,
                points=5.0,
                statement="Explique o algoritmo QuickSort.",
                reference_answer="Algoritmo de divisão e conquista...",
                rubric="Avaliar explicação do particionamento.",
            ),
        ]
    )

    # Assert
    assert len(config.questions) == 2
    assert config.questions[0].type == "choice"
    assert config.questions[1].type == "open"


def test_choice_question_when_correct_option_not_in_options_should_fail():
    with pytest.raises(ValidationError) as exc_info:
        ChoiceQuestionConfig(
            id=1,
            points=2.5,
            statement="Qual a cor do céu?",
            options=[
                ChoiceOptionConfig(id="a", text="Azul"),
                ChoiceOptionConfig(id="b", text="Verde"),
            ],
            correct_option_id="c",
        )
    assert "correct_option_id 'c' não coincide com nenhuma opção" in str(exc_info.value)


def test_assignment_create_request_when_code_type_matches_config():
    req = AssignmentCreateRequest(
        title="Exercício de Grafos",
        description="Implemente BFS",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config=CodeAssignmentConfig(
            languages=[LanguageConfig(name="python3", starter_code="")],
            test_cases=[TestCaseConfig(id=1, input="1\n", expected_output="1\n")],
        ),
    )
    assert req.type == AssignmentType.CODE
    assert isinstance(req.config, CodeAssignmentConfig)


def test_assignment_create_request_when_type_mismatches_config_should_fail():
    with pytest.raises(ValidationError):
        AssignmentCreateRequest(
            title="Questionário",
            description="Múltipla escolha",
            type=AssignmentType.QUESTIONNAIRE,
            config=CodeAssignmentConfig(
                languages=[LanguageConfig(name="python3", starter_code="")],
                test_cases=[],
            ),
        )


def test_assignment_student_response_sanitizes_sensitive_fields():
    # Arrange
    raw_config = {
        "questions": [
            {
                "id": 1,
                "type": "choice",
                "points": 2.5,
                "statement": "Qual a complexidade?",
                "options": [
                    {"id": "a", "text": "O(1)"},
                    {"id": "b", "text": "O(n)"},
                ],
                "correct_option_id": "b",
            },
            {
                "id": 2,
                "type": "open",
                "points": 5.0,
                "statement": "Explique tabelas hash.",
                "reference_answer": "Resposta secreta do professor",
                "rubric": "Rubrica confidencial da IA",
            },
        ]
    }

    # Act
    student_resp = AssignmentStudentResponse.model_validate(
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "classroom_id": "22222222-2222-2222-2222-222222222222",
            "title": "Questionário Avaliativo",
            "description": "Prova Bimestral",
            "type": AssignmentType.QUESTIONNAIRE,
            "release_policy": ReleasePolicyType.ON_REVIEW,
            "deadline": None,
            "config": raw_config,
            "created_at": "2026-09-23T20:00:00Z",
        }
    )

    # Assert: Nenhuma chave sensível deve vazar
    serialized = student_resp.model_dump()
    questions = serialized["config"]["questions"]
    assert "correct_option_id" not in questions[0]
    assert "reference_answer" not in questions[1]
    assert "rubric" not in questions[1]


def test_assignment_create_request_when_code_with_immediate_policy_should_fail():
    with pytest.raises(ValidationError) as exc_info:
        AssignmentCreateRequest(
            title="Código Proibido Imediato",
            type=AssignmentType.CODE,
            release_policy=ReleasePolicyType.IMMEDIATE,
            config=CodeAssignmentConfig(
                languages=[LanguageConfig(name="python3", starter_code="")],
                test_cases=[],
            ),
        )
    assert "não é permitida para atividades de código" in str(exc_info.value)


def test_assignment_create_request_when_questionnaire_with_open_and_immediate_policy_should_fail():
    with pytest.raises(ValidationError) as exc_info:
        AssignmentCreateRequest(
            title="Questionário com Dissertativa Proibido Imediato",
            type=AssignmentType.QUESTIONNAIRE,
            release_policy=ReleasePolicyType.IMMEDIATE,
            config=QuestionnaireAssignmentConfig(
                questions=[
                    OpenQuestionConfig(
                        id=1,
                        points=10.0,
                        statement="Explique recursão.",
                        reference_answer="Resposta...",
                    )
                ]
            ),
        )
    assert "restrita a questionários 100% objetivos" in str(exc_info.value)


def test_assignment_create_request_when_questionnaire_all_choice_with_immediate_policy_should_succeed():
    req = AssignmentCreateRequest(
        title="Questionário 100% Objetivo Imediato",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.IMMEDIATE,
        config=QuestionnaireAssignmentConfig(
            questions=[
                ChoiceQuestionConfig(
                    id=1,
                    points=10.0,
                    statement="Questão 1",
                    options=[
                        ChoiceOptionConfig(id="a", text="Opção A"),
                        ChoiceOptionConfig(id="b", text="Opção B"),
                    ],
                    correct_option_id="a",
                )
            ]
        ),
    )
    assert req.release_policy == ReleasePolicyType.IMMEDIATE
