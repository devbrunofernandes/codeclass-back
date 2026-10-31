import pytest
from httpx import AsyncClient

from app.infrastructure.runner.factory import get_runner_provider
from app.models.enums import TestRunVerdict
from app.schemas.assignment import TestCaseConfig
from tests.fixtures.tenants import TenantContext


@pytest.mark.live("runner")
@pytest.mark.parametrize(
    ("code", "verdict", "passed"),
    [
        (
            "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)",
            TestRunVerdict.ACCEPTED,
            1,
        ),
        ("print(0)", TestRunVerdict.WRONG_ANSWER, 0),
        ("raise RuntimeError('live runner failure')", TestRunVerdict.RUNTIME_ERROR, 0),
        ("while True: pass", TestRunVerdict.TIME_LIMIT_EXCEEDED, 0),
    ],
    ids=["accepted", "wrong-answer", "runtime-error", "timeout"],
)
@pytest.mark.asyncio
async def test_runner_live_real_network_execution_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    code: str,
    verdict: TestRunVerdict,
    passed: int,
) -> None:
    """Teste de Integração Real (Live): submete código real para o executor remoto configurado em settings.RUNNER_API_URL,

    validando credenciais reais, compilação/execução remota e veredito final da sandbox.
    """
    # 1. Arrange: Professor cria sala e matricula o aluno
    class_resp = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma Live Runner"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_resp.status_code == 201
    classroom_id = class_resp.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Professor cria atividade de código
    assignment_resp = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Soma de Dois Números Live",
            "description": "Leia a e b e imprima a + b.",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "statement": "Implemente a solução conforme os casos de teste.",
                "languages": [{"name": "python3"}],
                "time_limit_sec": 3.0,
                "memory_limit_mb": 128,
                "test_cases": [
                    {"id": 1, "input": "10 20\n", "expected_output": "30\n"},
                ],
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assignment_resp.status_code == 201
    assignment_id = assignment_resp.json()["id"]

    # 3. Aluno envia código Python real para o executor remoto
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/test-run",
        json={
            "language": "python3",
            "code": code,
            "test_cases": [{"id": 1, "input": "10 20\n", "expected_output": "30\n"}],
        },
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["overall_status"] == verdict
    assert data["total_tests"] == 1
    assert data["passed_tests"] == passed
    assert data["results"][0]["status"] == verdict
    if verdict == TestRunVerdict.ACCEPTED:
        assert "30" in data["results"][0]["stdout"]


@pytest.mark.live("runner")
@pytest.mark.asyncio
async def test_runner_live_execution_above_default_timeout_should_complete() -> None:
    results = await get_runner_provider().execute_batch(
        code="import time\ntime.sleep(16)\nprint('ok')",
        language="python3",
        test_cases=[TestCaseConfig(id=1, input="", expected_output="ok\n")],
        time_limit_sec=20,
        memory_limit_mb=128,
    )

    assert results[0].status == TestRunVerdict.ACCEPTED
    assert results[0].stdout == "ok\n"


@pytest.mark.live("runner")
@pytest.mark.asyncio
async def test_runner_live_cpu_above_three_seconds_should_complete() -> None:
    results = await get_runner_provider().execute_batch(
        code="import time\nstart = time.process_time()\nwhile time.process_time() - start < 4: pass\nprint('ok')",
        language="python3",
        test_cases=[TestCaseConfig(id=1, input="", expected_output="ok\n")],
        time_limit_sec=10,
        memory_limit_mb=128,
    )

    assert results[0].status == TestRunVerdict.ACCEPTED
