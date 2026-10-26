from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType
from app.schemas.assignment import AssignmentUpdateRequest
from app.services.assignment_service import AssignmentService


@pytest.mark.asyncio
async def test_update_assignment_when_statement_changes_should_persist_and_sanitize():
    assignment = Assignment(
        id=uuid4(),
        classroom_id=uuid4(),
        title="Soma",
        description="Resumo",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        created_at=datetime.now(UTC),
        config={
            "statement": "Original",
            "languages": [{"name": "python3"}],
            "rubric": "Critério privado",
        },
    )
    request = AssignmentUpdateRequest(
        config={
            **assignment.config,
            "statement": "  Some dois números.\nImprima o resultado.  ",
        }
    )
    db = AsyncMock()

    service = AssignmentService()
    await service.update_assignment(assignment, request, db)
    student = service.serialize_assignment_for_member(assignment, is_student=True)

    assert assignment.config["statement"] == "Some dois números.\nImprima o resultado."
    assert student.model_dump()["config"]["statement"] == assignment.config["statement"]
    assert "rubric" not in student.model_dump()["config"]
    assert assignment.description == "Resumo"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("is_student", [True, False])
def test_serialize_assignment_when_legacy_config_should_allow_missing_statement(
    is_student,
):
    assignment = Assignment(
        id=uuid4(),
        classroom_id=uuid4(),
        title="Legado",
        description="Resumo antigo",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        created_at=datetime.now(UTC),
        config={
            "languages": [{"name": "python3"}],
            "time_limit_sec": 2,
            "memory_limit_mb": 128,
            "test_cases": [],
        },
    )

    response = AssignmentService().serialize_assignment_for_member(
        assignment, is_student
    )

    assert response.model_dump()["config"]["statement"] == ""
