import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.exceptions import RunnerError, RunnerTimeoutError
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, TestRunVerdict
from tests.fixtures.runner import MockRunnerProvider
from tests.fixtures.tenants import TenantContext


@pytest.mark.asyncio
async def test_test_run_success_student_should_return_200_accepted(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    mock_runner_provider: MockRunnerProvider,
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    mock_runner_provider.default_verdict = TestRunVerdict.ACCEPTED

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == TestRunVerdict.ACCEPTED
    assert data["total_tests"] == 1
    assert data["passed_tests"] == 1
    assert data["execution_time_ms"] >= 0
    assert len(data["results"]) == 1
    assert data["results"][0]["status"] == TestRunVerdict.ACCEPTED


@pytest.mark.asyncio
async def test_test_run_student_tle_should_return_200_time_limit_exceeded(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    mock_runner_provider: MockRunnerProvider,
    tle_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    mock_runner_provider.default_verdict = TestRunVerdict.TIME_LIMIT_EXCEEDED

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=tle_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == TestRunVerdict.TIME_LIMIT_EXCEEDED
    assert data["results"][0]["status"] == TestRunVerdict.TIME_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_test_run_student_wrong_answer_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    mock_runner_provider: MockRunnerProvider,
    wrong_answer_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    mock_runner_provider.default_verdict = TestRunVerdict.WRONG_ANSWER

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=wrong_answer_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == TestRunVerdict.WRONG_ANSWER
    assert data["passed_tests"] == 0


@pytest.mark.asyncio
async def test_test_run_teacher_can_execute_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.teacher.auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["overall_status"] == TestRunVerdict.ACCEPTED


@pytest.mark.asyncio
async def test_test_run_admin_and_owner_can_execute_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    # Admin
    admin_resp = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.admin.auth_headers,
    )
    assert admin_resp.status_code == 200

    # Owner
    owner_resp = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.owner.auth_headers,
    )
    assert owner_resp.status_code == 200


@pytest.mark.asyncio
async def test_test_run_when_questionnaire_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.QUESTIONNAIRE
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "Apenas atividades do tipo código" in response.json()["detail"]


@pytest.mark.asyncio
async def test_test_run_when_language_not_allowed_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json={"language": "rust", "code": "fn main() {}"},
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "não é permitida para esta atividade" in response.json()["detail"]


@pytest.mark.asyncio
async def test_test_run_when_no_test_cases_configured_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student,
        type=AssignmentType.CODE,
        config={
            "languages": [{"name": "python3"}],
            "time_limit_sec": 2.0,
            "memory_limit_mb": 128,
            "test_cases": [],
        },
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "não possui casos de teste configurados" in response.json()["detail"]


@pytest.mark.asyncio
async def test_test_run_without_auth_token_should_return_401(
    async_client: AsyncClient,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_test_run_unenrolled_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    # other_student é membro da org, mas não está matriculado nesta turma
    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.other_student.auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_test_run_teacher_of_another_classroom_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    # other_teacher não é o professor responsável por esta sala nem admin/owner
    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.other_teacher.auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_test_run_other_organization_member_should_return_403(
    async_client: AsyncClient,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    create_tenant: Callable[[str], Awaitable[TenantContext]],
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    other_tenant = await create_tenant("Outra Instituição")

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=other_tenant.student.auth_headers,
    )

    assert response.status_code == 403
    assert "Acesso negado a recursos de outra organização" in response.json()["detail"]


@pytest.mark.asyncio
async def test_test_run_nonexistent_assignment_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    valid_test_run_payload: dict[str, str],
) -> None:
    response = await async_client.post(
        f"/api/v1/assignments/{uuid.uuid4()}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_test_run_invalid_schema_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json={"language": ""},  # sem code e com language vazia
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_test_run_external_runner_failure_should_return_502(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    mock_runner_provider: MockRunnerProvider,
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    mock_runner_provider.force_error = RunnerError(
        "Erro na conexão com executor remoto.", status_code=502
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 502
    assert "Erro na conexão com executor remoto." in response.json()["detail"]


@pytest.mark.asyncio
async def test_test_run_external_runner_timeout_should_return_504(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_assignment: Callable[..., Awaitable[Assignment]],
    mock_runner_provider: MockRunnerProvider,
    valid_test_run_payload: dict[str, str],
) -> None:
    assignment = await create_assignment(
        classroom_with_student, type=AssignmentType.CODE
    )
    mock_runner_provider.force_error = RunnerTimeoutError(
        "Timeout da infraestrutura do executor.", status_code=504
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment.id}/test-run",
        json=valid_test_run_payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 504
    assert "Timeout da infraestrutura do executor." in response.json()["detail"]
