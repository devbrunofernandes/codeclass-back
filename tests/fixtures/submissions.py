from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, ReleasePolicyType


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
