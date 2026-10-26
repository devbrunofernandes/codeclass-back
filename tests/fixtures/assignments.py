import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import (
    AssignmentType,
    ReleasePolicyType,
    SubmissionStatus,
)
from app.models.submission import Submission
from tests.fixtures.tenants import TenantContext


@pytest.fixture
def create_assignment(
    db_session: AsyncSession,
) -> Callable[..., Awaitable[Assignment]]:
    """Factory flexível para instanciar tarefas de qualquer tipo e política."""

    async def _create(
        classroom: Classroom,
        title: str = "Tarefa Padrão",
        description: str = "Descrição da Tarefa",
        type: AssignmentType = AssignmentType.CODE,
        release_policy: ReleasePolicyType = ReleasePolicyType.ON_REVIEW,
        deadline: datetime | None = None,
        config: dict[str, Any] | None = None,
    ) -> Assignment:
        if config is None:
            if type == AssignmentType.CODE:
                config = {
                    "statement": "Implemente a solução conforme os casos de teste.",
                    "languages": [
                        {
                            "name": "python3",
                            "starter_code": "def solution():\n    pass\n",
                        }
                    ],
                    "time_limit_sec": 2.0,
                    "memory_limit_mb": 128,
                    "rubric": "Avaliar corretude e complexidade.",
                    "test_cases": [
                        {"id": 1, "input": "1 2\n", "expected_output": "3\n"}
                    ],
                }
            else:
                config = {
                    "questions": [
                        {
                            "id": 1,
                            "type": "choice",
                            "points": 10.0,
                            "statement": "Qual a complexidade do quicksort no caso médio?",
                            "options": [
                                {"id": "a", "text": "O(n log n)"},
                                {"id": "b", "text": "O(n^2)"},
                            ],
                            "correct_option_id": "a",
                        }
                    ]
                }

        a = Assignment(
            id=uuid.uuid4(),
            classroom_id=classroom.id,
            title=title,
            description=description,
            type=type,
            release_policy=release_policy,
            deadline=deadline or (datetime.now(UTC) + timedelta(days=7)),
            config=config,
        )
        db_session.add(a)
        await db_session.commit()
        return a

    return _create


@pytest.fixture
async def assignment_without_submissions(
    classroom: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> Assignment:
    """Fixture que instancia uma tarefa de código limpa sem submissões vinculadas."""
    return await create_assignment(
        classroom=classroom,
        title="Busca Binária",
        description="Implemente o algoritmo de busca binária",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=datetime.now(UTC) + timedelta(days=7),
        config={
            "statement": "Implemente a solução conforme os casos de teste.",
            "languages": [
                {
                    "name": "python3",
                    "starter_code": "def binary_search(arr, target):\n    pass\n",
                }
            ],
            "time_limit_sec": 2.0,
            "memory_limit_mb": 128,
            "rubric": "Avaliar tratamento para elemento não encontrado.",
            "test_cases": [
                {"id": 1, "input": "[1, 2, 3] 2\n", "expected_output": "1\n"}
            ],
        },
    )


@pytest.fixture
async def assignment_with_submissions(
    tenant: TenantContext,
    classroom: Classroom,
    enrolled_student: ClassroomStudent,
    create_assignment: Callable[..., Awaitable[Assignment]],
    db_session: AsyncSession,
) -> Assignment:
    """Fixture que instancia uma tarefa com submissão ativa de aluno vinculada."""
    a = await create_assignment(
        classroom=classroom,
        title="Questionário de Grafos",
        description="Questões sobre busca em largura e profundidade",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=datetime.now(UTC) + timedelta(days=3),
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "Qual estrutura de dados é usada na BFS?",
                    "options": [
                        {"id": "a", "text": "Pilha"},
                        {"id": "b", "text": "Fila"},
                    ],
                    "correct_option_id": "b",
                }
            ]
        },
    )

    sub = Submission(
        id=uuid.uuid4(),
        assignment_id=a.id,
        student_id=tenant.student.user.id,
        content={"answers": [{"question_id": 1, "selected_option_id": "b"}]},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(sub)
    await db_session.commit()
    return a


from dataclasses import dataclass
from decimal import Decimal


@dataclass
class StudentAssignmentsBundle:
    classroom: Classroom
    pending_assignment: Assignment
    overdue_assignment: Assignment
    draft_assignment: Assignment
    submitted_assignment: Assignment
    graded_assignment: Assignment
    draft_submission: Submission
    submitted_submission: Submission
    graded_submission: Submission


@pytest.fixture
async def student_assignments_bundle(
    tenant: TenantContext,
    classroom: Classroom,
    enrolled_student: ClassroomStudent,
    create_assignment: Callable[..., Awaitable[Assignment]],
    db_session: AsyncSession,
) -> StudentAssignmentsBundle:
    """Fixture completa com todos os status de atividades para o estudante."""
    now = datetime.now(UTC)

    # 1. Atividade pendente (sem submissão, dentro do prazo)
    pending_a = await create_assignment(
        classroom=classroom,
        title="Atividade Pendente",
        description="Dentro do prazo e sem entrega",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=now + timedelta(days=5),
    )

    # 2. Atividade atrasada (sem submissão, prazo vencido)
    overdue_a = await create_assignment(
        classroom=classroom,
        title="Atividade Atrasada",
        description="Prazo expirado e sem entrega",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=now - timedelta(days=2),
    )

    # 3. Atividade com rascunho (dentro do prazo, submissão draft)
    draft_a = await create_assignment(
        classroom=classroom,
        title="Atividade em Rascunho",
        description="Com rascunho salvo mas não entregue formalmente",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=now + timedelta(days=5),
    )
    draft_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=draft_a.id,
        student_id=tenant.student.user.id,
        content={"code": "def draft(): pass", "language": "python3"},
        status=SubmissionStatus.DRAFT,
    )
    db_session.add(draft_sub)

    # 4. Atividade entregue (formalmente entregue, aguardando avaliação)
    submitted_a = await create_assignment(
        classroom=classroom,
        title="Atividade Entregue",
        description="Submetida formalmente",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=now + timedelta(days=5),
    )
    submitted_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=submitted_a.id,
        student_id=tenant.student.user.id,
        content={"code": "def solution(): return 42", "language": "python3"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(submitted_sub)

    # 5. Atividade avaliada (publicada com nota)
    graded_a = await create_assignment(
        classroom=classroom,
        title="Atividade Avaliada",
        description="Nota publicada",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        deadline=now - timedelta(days=3),
    )
    graded_sub = Submission(
        id=uuid.uuid4(),
        assignment_id=graded_a.id,
        student_id=tenant.student.user.id,
        content={"code": "def solution(): return 100", "language": "python3"},
        grade=Decimal("9.50"),
        status=SubmissionStatus.PUBLISHED,
    )
    db_session.add(graded_sub)

    await db_session.commit()

    return StudentAssignmentsBundle(
        classroom=classroom,
        pending_assignment=pending_a,
        overdue_assignment=overdue_a,
        draft_assignment=draft_a,
        submitted_assignment=submitted_a,
        graded_assignment=graded_a,
        draft_submission=draft_sub,
        submitted_submission=submitted_sub,
        graded_submission=graded_sub,
    )
