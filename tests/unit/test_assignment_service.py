import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import Submission
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    CodeAssignmentConfig,
    LanguageConfig,
    TestCaseConfig,
)
from app.services.assignment_service import assignment_service
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_assignment_service_create_and_list_assignment(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    req = AssignmentCreateRequest(
        title="Busca Binária",
        description="Implemente o algoritmo",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config=CodeAssignmentConfig(
            languages=[LanguageConfig(name="python3", starter_code="")],
            test_cases=[TestCaseConfig(id=1, input="1\n", expected_output="1\n")],
        ),
    )

    # Act
    created = await assignment_service.create_assignment(classroom, req, db_session)

    # Assert
    assert created.id is not None
    assert created.classroom_id == classroom.id
    assert created.title == "Busca Binária"

    # List
    assignments = await assignment_service.list_assignments_by_classroom(
        classroom.id, db_session
    )
    assert len(assignments) == 1
    assert assignments[0].id == created.id


@pytest.mark.asyncio
async def test_assignment_service_update_assignment(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    assignment = Assignment(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        title="Original",
        description="Original",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "Qual a complexidade?",
                    "options": [
                        {"id": "a", "text": "O(1)"},
                        {"id": "b", "text": "O(n)"},
                    ],
                    "correct_option_id": "a",
                }
            ]
        },
    )
    db_session.add(assignment)
    await db_session.commit()

    update_req = AssignmentUpdateRequest(
        title="Título Atualizado",
        description="Descrição Atualizada",
        release_policy=ReleasePolicyType.IMMEDIATE,
    )

    # Act
    updated = await assignment_service.update_assignment(
        assignment, update_req, db_session
    )

    # Assert
    assert updated.title == "Título Atualizado"
    assert updated.description == "Descrição Atualizada"
    assert updated.release_policy == ReleasePolicyType.IMMEDIATE


@pytest.mark.asyncio
async def test_assignment_service_delete_when_has_submissions_raises_bad_request(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    assignment = Assignment(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        title="Tarefa com submissão",
        description="",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={},
    )
    db_session.add(assignment)
    await db_session.flush()

    sub = Submission(
        id=uuid.uuid4(),
        assignment_id=assignment.id,
        student_id=tenant.student.user.id,
        content={"code": "print(1)"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(sub)
    await db_session.commit()

    # Act & Assert
    with pytest.raises(BadRequestException) as exc_info:
        await assignment_service.delete_assignment(assignment, db_session)

    assert "submissões vinculadas" in str(exc_info.value.message)
