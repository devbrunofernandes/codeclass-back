import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.enums import TestRunVerdict
from tests.fixtures.tenants import TenantContext


@pytest.mark.live
@pytest.mark.skipif(
    not (
        settings.RUNNER_API_KEY
        or (settings.RUNNER_PROVIDER == "piston" and settings.RUNNER_API_URL)
    ),
    reason="Runner remoto/local não configurado no ambiente para testes com rede real.",
)
@pytest.mark.asyncio
async def test_runner_live_real_network_execution_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
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
    code = "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)"
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/test-run",
        json={"language": "python3", "code": code},
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["overall_status"] == TestRunVerdict.ACCEPTED
    assert data["total_tests"] == 1
    assert data["passed_tests"] == 1
    assert data["results"][0]["status"] == TestRunVerdict.ACCEPTED
    assert data["results"][0]["stdout"] is not None
    assert "30" in data["results"][0]["stdout"]
