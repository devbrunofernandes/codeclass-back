import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import BadRequestException
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType, TestRunVerdict
from app.schemas.runner import TestCaseResult, TestRunRequest
from app.services.runner_service import RunnerService


def make_assignment(
    assignment_type: AssignmentType = AssignmentType.CODE,
    languages: list[str] | None = None,
    test_cases: list[dict] | None = None,
    time_limit_sec: float = 2.0,
    memory_limit_mb: int = 128,
) -> Assignment:
    langs = [{"name": l} for l in (languages or ["python3"])]
    tcs = (
        test_cases
        if test_cases is not None
        else [{"id": 1, "input": "1\n", "expected_output": "1\n"}]
    )
    return Assignment(
        id=uuid.uuid4(),
        classroom_id=uuid.uuid4(),
        title="Tarefa de Teste",
        description="Descrição",
        type=assignment_type,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "languages": langs,
            "time_limit_sec": time_limit_sec,
            "memory_limit_mb": memory_limit_mb,
            "test_cases": tcs,
        },
    )


@pytest.mark.asyncio
async def test_runner_service_rejects_non_code_assignment() -> None:
    service = RunnerService()
    assignment = make_assignment(assignment_type=AssignmentType.QUESTIONNAIRE)
    request = TestRunRequest(language="python3", code="print(1)")

    with pytest.raises(BadRequestException, match="Apenas atividades do tipo código"):
        await service.execute_test_run(assignment, request)


@pytest.mark.asyncio
async def test_runner_service_rejects_unallowed_language() -> None:
    service = RunnerService()
    assignment = make_assignment(languages=["python3"])
    request = TestRunRequest(language="javascript", code="console.log(1)")

    with pytest.raises(
        BadRequestException, match="não é permitida para esta atividade"
    ):
        await service.execute_test_run(assignment, request)


@pytest.mark.asyncio
async def test_runner_service_rejects_empty_test_cases() -> None:
    service = RunnerService()
    assignment = make_assignment(test_cases=[])
    request = TestRunRequest(language="python3", code="print(1)")

    with pytest.raises(
        BadRequestException, match="não possui casos de teste configurados"
    ):
        await service.execute_test_run(assignment, request)


@pytest.mark.asyncio
async def test_runner_service_computes_overall_status_accepted() -> None:
    service = RunnerService()
    assignment = make_assignment()
    request = TestRunRequest(language="python3", code="print(1)")

    mock_provider = AsyncMock()
    mock_provider.execute_batch.return_value = [
        TestCaseResult(test_case_id=1, status=TestRunVerdict.ACCEPTED, time_sec=0.01)
    ]

    with patch(
        "app.services.runner_service.get_runner_provider", return_value=mock_provider
    ):
        response = await service.execute_test_run(assignment, request)

    assert response.overall_status == TestRunVerdict.ACCEPTED
    assert response.total_tests == 1
    assert response.passed_tests == 1
    assert response.execution_time_ms >= 0
    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_runner_service_computes_overall_status_failure_priority() -> None:
    service = RunnerService()
    assignment = make_assignment(
        test_cases=[
            {"id": 1, "input": "1\n", "expected_output": "1\n"},
            {"id": 2, "input": "2\n", "expected_output": "2\n"},
        ]
    )
    request = TestRunRequest(language="python3", code="print(1)")

    mock_provider = AsyncMock()
    mock_provider.execute_batch.return_value = [
        TestCaseResult(test_case_id=1, status=TestRunVerdict.ACCEPTED, time_sec=0.01),
        TestCaseResult(
            test_case_id=2, status=TestRunVerdict.WRONG_ANSWER, time_sec=0.02
        ),
    ]

    with patch(
        "app.services.runner_service.get_runner_provider", return_value=mock_provider
    ):
        response = await service.execute_test_run(assignment, request)

    assert response.overall_status == TestRunVerdict.WRONG_ANSWER
    assert response.total_tests == 2
    assert response.passed_tests == 1
