from unittest.mock import AsyncMock, patch

import pytest

from app.infrastructure.ai.base import AiProvider
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType
from app.schemas.submission import AiInsightResult, AiItemInsightSchema
from app.services.ai_service import AiService


@pytest.fixture
def dummy_code_assignment() -> Assignment:
    assignment = Assignment(
        title="Busca Binária",
        description="Implemente busca binária recursiva ou iterativa",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "max_grade": 10.0,
            "languages": [{"name": "python3"}],
            "rubrics": "Complexidade O(log n) e tratamento de lista vazia.",
        },
    )
    return assignment


@pytest.fixture
def dummy_questionnaire_assignment() -> Assignment:
    assignment = Assignment(
        title="Estruturas de Dados",
        description="Questionário misto",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 4.0,
                    "correct_option_id": "b",
                },
                {
                    "id": 2,
                    "type": "open",
                    "points": 6.0,
                    "prompt": "Explique tabelas hash.",
                    "reference_answer": "Estrutura com buckets e encadeamento.",
                },
            ]
        },
    )
    return assignment


@pytest.mark.asyncio
async def test_evaluate_code_submission_success(dummy_code_assignment: Assignment):
    mock_provider = AsyncMock(spec=AiProvider)
    mock_provider.generate_structured_insight.return_value = AiInsightResult(
        suggested_grade=9.5,
        max_grade=10.0,
        strengths=["Código limpo", "Complexidade O(log n) garantida"],
        improvements=["Adicionar type hints"],
        reasoning="A solução atende aos critérios com excelência.",
        item_insights=None,
    )

    service = AiService(provider=mock_provider)

    result = await service.evaluate_code_submission(
        assignment=dummy_code_assignment,
        code="def binary_search(arr, x): pass",
        language="python3",
    )

    assert result.suggested_grade == 9.5
    assert result.max_grade == 10.0
    assert len(result.strengths) == 2
    assert result.reasoning == "A solução atende aos critérios com excelência."
    assert result.item_insights is None
    mock_provider.generate_structured_insight.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_questionnaire_submission_success(
    dummy_questionnaire_assignment: Assignment,
):
    mock_provider = AsyncMock(spec=AiProvider)
    # Pergunta 1: choice (correta -> 4.0 pts)
    # Pergunta 2: open (avaliada pela IA -> 5.5 pts de 6.0)
    mock_provider.generate_structured_insight.return_value = AiInsightResult(
        suggested_grade=5.5,
        max_grade=6.0,
        strengths=["Boa explicação sobre os buckets"],
        improvements=["Poderia mencionar função hash"],
        reasoning="Explicou os conceitos centrais adequadamente.",
        item_insights=[
            AiItemInsightSchema(
                question_id=2,
                suggested_grade=5.5,
                max_grade=6.0,
                strengths=["Explicou buckets"],
                improvements=["Não citou colisão"],
                reasoning="Boa compreensão.",
            )
        ],
    )

    service = AiService(provider=mock_provider)

    answers = [
        {"question_id": 1, "selected_option_id": "b"},
        {
            "question_id": 2,
            "text_answer": "Tabela hash usa buckets para guardar elementos colididos.",
        },
    ]

    result = await service.evaluate_questionnaire_submission(
        assignment=dummy_questionnaire_assignment,
        answers=answers,
    )

    # 4.0 (objetiva) + 5.5 (dissertativa) = 9.5 total
    assert result.suggested_grade == 9.5
    assert result.max_grade == 10.0
    assert result.item_insights is not None
    assert len(result.item_insights) == 1
    assert result.item_insights[0].question_id == 2
    mock_provider.generate_structured_insight.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_submission_dispatcher_code(dummy_code_assignment: Assignment):
    service = AiService()
    expected = AiInsightResult(
        suggested_grade=10.0,
        max_grade=10.0,
        strengths=["Perfeito"],
        improvements=[],
        reasoning="100%",
    )

    with patch.object(
        service, "evaluate_code_submission", new_callable=AsyncMock
    ) as mock_eval:
        mock_eval.return_value = expected
        result = await service.evaluate_submission(
            assignment=dummy_code_assignment,
            submission_content={"language": "python3", "code": "pass"},
        )

    assert result == expected
    mock_eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_submission_dispatcher_questionnaire(
    dummy_questionnaire_assignment: Assignment,
):
    service = AiService()
    expected = AiInsightResult(
        suggested_grade=8.0,
        max_grade=10.0,
        strengths=["Bom"],
        improvements=[],
        reasoning="OK",
    )

    with patch.object(
        service, "evaluate_questionnaire_submission", new_callable=AsyncMock
    ) as mock_eval:
        mock_eval.return_value = expected
        result = await service.evaluate_submission(
            assignment=dummy_questionnaire_assignment,
            submission_content={
                "answers": [{"question_id": 1, "selected_option_id": "b"}]
            },
        )

    assert result == expected
    mock_eval.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluate_submission_unsupported_type():
    assignment = Assignment(
        title="Atividade Inválida",
        type="unsupported_type",  # type: ignore[arg-type]
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={},
    )
    service = AiService()
    with pytest.raises(ValueError, match="Tipo de atividade não suportado pela IA"):
        await service.evaluate_submission(
            assignment=assignment,
            submission_content={},
        )


def test_ai_service_provider_property_lazy_initialization():
    service = AiService()
    with patch("app.services.ai_service.get_ai_provider") as mock_get_provider:
        mock_get_provider.return_value = "custom_provider"
        provider = service.provider
        assert provider == "custom_provider"
        mock_get_provider.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_questionnaire_clamping_grade_does_not_exceed_max(
    dummy_questionnaire_assignment: Assignment,
):
    """Garante que nota sugerida pela IA é limitada a total_max_points mesmo se alucinar nota inflada."""
    mock_provider = AsyncMock(spec=AiProvider)
    # Total da atividade é 10.0 (4.0 obj + 6.0 open). Simulamos que a IA alucinou 99.0 na dissertativa.
    mock_provider.generate_structured_insight.return_value = AiInsightResult(
        suggested_grade=99.0,
        max_grade=6.0,
        strengths=["Ótimo"],
        improvements=[],
        reasoning="Alucinação com nota astronômica",
        item_insights=[
            AiItemInsightSchema(
                question_id=2,
                suggested_grade=99.0,
                max_grade=6.0,
                strengths=["Excelente"],
                improvements=[],
                reasoning="Exagerado.",
            )
        ],
    )

    service = AiService(provider=mock_provider)
    answers = [
        {"question_id": 1, "selected_option_id": "b"},  # 4.0 pts
        {"question_id": 2, "text_answer": "Resposta teste"},
    ]

    result = await service.evaluate_questionnaire_submission(
        assignment=dummy_questionnaire_assignment,
        answers=answers,
    )

    # 4.0 + 99.0 = 103.0 -> Deve ser travado no total_max_points = 10.0
    assert result.suggested_grade == 10.0
    assert result.max_grade == 10.0
