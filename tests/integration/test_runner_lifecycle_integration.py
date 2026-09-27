import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TestRunVerdict
from app.models.submission import Submission, SubmissionEvaluation
from tests.fixtures.runner import MockRunnerProvider
from tests.fixtures.tenants import TenantContext


@pytest.mark.asyncio
async def test_runner_lifecycle_and_ephemeral_guarantee_integration(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
    mock_runner_provider: MockRunnerProvider,
) -> None:
    """Valida o ciclo de vida completo do Test-Run no PostgreSQL real e a garantia estrita de efemeridade (RNF01 / RF17)."""
    # 1. Arrange: Professor cria sala e matricula o aluno
    class_resp = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Estruturas de Dados - Lifecycle Runner"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_resp.status_code == 201
    classroom_id = class_resp.json()["id"]

    enroll_resp = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    assert enroll_resp.status_code == 201

    # 2. Professor cria atividade de código com 2 casos de teste
    assignment_resp = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Soma Simples",
            "description": "Leia dois inteiros e imprima a soma.",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "languages": [
                    {
                        "name": "python3",
                        "starter_code": "import sys\n# implemente sua solucao\n",
                    }
                ],
                "time_limit_sec": 2.0,
                "memory_limit_mb": 128,
                "rubric": "Avaliar corretude e legibilidade.",
                "test_cases": [
                    {"id": 1, "input": "2 3\n", "expected_output": "5\n"},
                    {"id": 2, "input": "-1 1\n", "expected_output": "0\n"},
                ],
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assignment_resp.status_code == 201
    assignment_id = assignment_resp.json()["id"]

    # 3. Aluno executa Test-Run experimental (Caminho Feliz)
    mock_runner_provider.default_verdict = TestRunVerdict.ACCEPTED
    run_resp = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/test-run",
        json={
            "language": "python3",
            "code": "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)",
        },
        headers=tenant.student.auth_headers,
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["overall_status"] == TestRunVerdict.ACCEPTED
    assert run_data["total_tests"] == 2
    assert run_data["passed_tests"] == 2
    assert len(run_data["results"]) == 2

    # 4. Aluno executa Test-Run experimental com resposta incorreta
    mock_runner_provider.default_verdict = TestRunVerdict.WRONG_ANSWER
    wrong_resp = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/test-run",
        json={
            "language": "python3",
            "code": "print(42)",
        },
        headers=tenant.student.auth_headers,
    )
    assert wrong_resp.status_code == 200
    wrong_data = wrong_resp.json()
    assert wrong_data["overall_status"] == TestRunVerdict.WRONG_ANSWER
    assert wrong_data["passed_tests"] == 0

    # 5. Assert de Efemeridade Inegociável (Zero linhas criadas em submissions e avaliações)
    submissions_count = await db_session.scalar(
        select(func.count()).select_from(Submission)
    )
    evaluations_count = await db_session.scalar(
        select(func.count()).select_from(SubmissionEvaluation)
    )

    assert submissions_count == 0, (
        "Falha de efemeridade: Test-Run criou linhas indevidas na tabela submissions!"
    )
    assert evaluations_count == 0, (
        "Falha de efemeridade: Test-Run criou linhas indevidas na tabela submission_evaluations!"
    )
