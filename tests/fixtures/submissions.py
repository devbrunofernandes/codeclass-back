import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
    SubmissionEvaluation,
)
from app.schemas.submission import AiInsightResult


@pytest.fixture
async def past_deadline_code_assignment(
    classroom: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> Assignment:
    """Instancia uma atividade cujo prazo já expirou."""
    return await create_assignment(
        classroom=classroom,
        title="Tarefa com Prazo Expirado",
        description="Prazo acabou ontem",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=datetime.now(UTC) - timedelta(days=1),
    )


@pytest.fixture
async def objective_questionnaire_assignment(
    classroom: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> Assignment:
    """Instancia um questionário 100% objetivo com política de liberação imediata."""
    return await create_assignment(
        classroom=classroom,
        title="Questionário 100% Objetivo",
        description="Apenas questões de múltipla escolha",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.IMMEDIATE,
        deadline=datetime.now(UTC) + timedelta(days=5),
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "2 + 2 é igual a?",
                    "options": [
                        {"id": "a", "text": "3"},
                        {"id": "b", "text": "4"},
                    ],
                    "correct_option_id": "b",
                },
                {
                    "id": 2,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "A Terra é plana?",
                    "options": [
                        {"id": "a", "text": "Sim"},
                        {"id": "b", "text": "Não"},
                    ],
                    "correct_option_id": "b",
                },
            ]
        },
    )


@pytest.fixture
async def objective_questionnaire_on_review(
    classroom: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> Assignment:
    """Instancia um questionário 100% objetivo com liberação retida sob avaliação docente."""
    return await create_assignment(
        classroom=classroom,
        title="Questionário Objetivo com Nota Retida",
        description="Liberação após revisão do professor",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=datetime.now(UTC) + timedelta(days=5),
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 10.0,
                    "statement": "Qual a capital do Brasil?",
                    "options": [
                        {"id": "a", "text": "Brasília"},
                        {"id": "b", "text": "São Paulo"},
                    ],
                    "correct_option_id": "a",
                }
            ]
        },
    )


@pytest.fixture
async def mixed_questionnaire_assignment(
    classroom: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> Assignment:
    """Instancia um questionário misto (objetivo + dissertativo) que requer IA."""
    return await create_assignment(
        classroom=classroom,
        title="Questionário Misto de Algoritmos",
        description="Contém questões objetivas e dissertativas",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=datetime.now(UTC) + timedelta(days=5),
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 4.0,
                    "statement": "Qual a complexidade de busca binária?",
                    "options": [
                        {"id": "a", "text": "O(1)"},
                        {"id": "b", "text": "O(log n)"},
                    ],
                    "correct_option_id": "b",
                },
                {
                    "id": 2,
                    "type": "open",
                    "points": 6.0,
                    "statement": "Explique o funcionamento da tabela hash com encadeamento separado.",
                    "reference_answer": "Cada posição da tabela aponta para uma lista encadeada onde elementos colididos são inseridos.",
                },
            ]
        },
    )


@pytest.fixture
def mock_ai_insight_code() -> dict:
    """Retorna um insight padrão de IA para submissão de código."""
    return {
        "suggested_grade": 9.0,
        "max_grade": 10.0,
        "strengths": [
            "Boa nomenclatura de variáveis e funções modulares",
            "Tratou adequadamente os casos de borda previstos na rubrica",
        ],
        "improvements": [
            "Poderia otimizar o consumo de memória evitando cópias desnecessárias de arrays"
        ],
        "reasoning": "A solução resolve o problema de forma limpa, elegante e aderente às boas práticas exigidas.",
        "item_insights": None,
    }


@pytest.fixture
def mock_ai_insight_questionnaire() -> dict:
    """Retorna um insight padrão de IA para questionário misto/dissertativo."""
    return {
        "suggested_grade": 8.5,
        "max_grade": 10.0,
        "strengths": [
            "Respostas conceituais precisas e coerentes com a resposta de referência"
        ],
        "improvements": ["Poderia aprofundar a justificativa teórica na questão 2"],
        "reasoning": "O estudante demonstrou domínio sólido do conteúdo, com pequenas omissões teóricas secundárias.",
        "item_insights": [
            {
                "question_id": 2,
                "suggested_grade": 4.5,
                "max_grade": 6.0,
                "strengths": [
                    "Explicou com clareza o encadeamento separado por bucket"
                ],
                "improvements": ["Não citou a degradação para O(n) no pior caso"],
                "reasoning": "Atendeu à rubrica essencial de estruturas dinâmicas.",
            }
        ],
    }


@pytest.fixture(autouse=True)
def mock_ai_service(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> AsyncMock | None:
    """Mock automático do AiService para evitar chamadas de rede externas.

    Se o teste estiver anotado com @pytest.mark.live, o mock é desativado para permitir a conexão real.
    """
    if request.node.get_closest_marker("live"):
        return None

    mock_evaluate = AsyncMock()

    async def _default_evaluate(
        assignment: Any, submission_content: Any
    ) -> AiInsightResult:
        max_grade = float(assignment.config.get("max_grade", 10.0))
        return AiInsightResult(
            suggested_grade=round(max_grade * 0.9, 2),
            max_grade=max_grade,
            strengths=["Código modular e legível", "Boas práticas observadas"],
            improvements=["Adicionar testes de borda"],
            reasoning="Parecer pedagógico gerado com sucesso.",
            item_insights=None,
        )

    mock_evaluate.side_effect = _default_evaluate
    monkeypatch.setattr(
        "app.services.submission_service.ai_service.evaluate_submission",
        mock_evaluate,
    )
    monkeypatch.setattr(
        "app.services.ai_service.ai_service.evaluate_submission",
        mock_evaluate,
    )
    return mock_evaluate


@pytest.fixture
def create_submission(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Submission]]:
    """Factory para instanciar submissões com status e dados arbitrários."""

    async def _create(
        assignment: Assignment,
        student_id: uuid.UUID,
        status: SubmissionStatus = SubmissionStatus.PENDING,
        grade: Decimal | None = None,
        content: dict[str, Any] | None = None,
        ai_insight_status: str | None = None,
        ai_insight_suggested_grade: Decimal | None = None,
        evaluation_grade: Decimal | None = None,
        evaluation_feedback: str | None = None,
        evaluation_detailed_scores: dict[str, Any] | None = None,
    ) -> Submission:
        if content is None:
            content = {"language": "python3", "code": "def solution(): return 42"}

        sub = Submission(
            assignment_id=assignment.id,
            student_id=student_id,
            status=status,
            grade=grade,
            content=content,
        )
        db_session.add(sub)
        await db_session.flush()

        if ai_insight_status:
            insight = SubmissionAiInsight(
                submission_id=sub.id,
                status=ai_insight_status,
                suggested_grade=ai_insight_suggested_grade,
                max_grade=Decimal("10.00"),
                reasoning="Parecer gerado pelo mock",
                strengths=["Boa legibilidade"],
                improvements=["Otimizar laço"],
            )
            db_session.add(insight)

        if evaluation_grade is not None:
            eval_record = SubmissionEvaluation(
                submission_id=sub.id,
                grade=evaluation_grade,
                general_feedback=evaluation_feedback or "Bom trabalho",
                detailed_scores=evaluation_detailed_scores or {},
            )
            db_session.add(eval_record)

        await db_session.commit()
        stmt = (
            select(Submission)
            .options(
                selectinload(Submission.assignment),
                selectinload(Submission.student),
                selectinload(Submission.ai_insight),
                selectinload(Submission.evaluation),
            )
            .where(Submission.id == sub.id)
        )
        res = await db_session.execute(stmt)
        return res.scalar_one()

    return _create


@pytest.fixture
async def submission_awaiting_review(
    assignment_without_submissions: Assignment,
    enrolled_student: ClassroomStudent,
    create_submission: Callable[..., Awaitable[Submission]],
) -> Submission:
    """Instancia uma submissão pronta para avaliação docente (status awaiting_review)."""
    return await create_submission(
        assignment=assignment_without_submissions,
        student_id=enrolled_student.student_id,
        status=SubmissionStatus.AWAITING_REVIEW,
        content={"language": "python3", "code": "def solution(): return 42\n"},
        ai_insight_status="completed",
        ai_insight_suggested_grade=Decimal("8.50"),
    )


@pytest.fixture
async def submission_published(
    assignment_without_submissions: Assignment,
    enrolled_student: ClassroomStudent,
    create_submission: Callable[..., Awaitable[Submission]],
) -> Submission:
    """Instancia uma submissão com avaliação formal publicada (status published)."""
    return await create_submission(
        assignment=assignment_without_submissions,
        student_id=enrolled_student.student_id,
        status=SubmissionStatus.PUBLISHED,
        grade=Decimal("9.00"),
        content={"language": "python3", "code": "def solution(): return 42\n"},
        ai_insight_status="completed",
        ai_insight_suggested_grade=Decimal("8.50"),
        evaluation_grade=Decimal("9.00"),
        evaluation_feedback="Excelente implementação do algoritmo!",
        evaluation_detailed_scores={
            "questions_evaluation": [
                {
                    "question_id": 1,
                    "awarded_points": 9.0,
                    "max_points": 10.0,
                    "teacher_feedback": "Muito bom!",
                }
            ]
        },
    )
