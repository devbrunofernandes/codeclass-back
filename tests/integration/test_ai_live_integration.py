import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.enums import SubmissionStatus
from app.models.submission import Submission
from tests.conftest import TenantContext


@pytest.mark.live
@pytest.mark.skipif(
    not settings.AI_API_KEY,
    reason="AI_API_KEY não configurada no ambiente.",
)
@pytest.mark.asyncio
async def test_ai_live_real_network_inference_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    """Teste de Integração Real (Live): executa chamada HTTPS real para a API do provedor de IA,

    validando credenciais, modelo configurado em settings.AI_MODEL, contrato de response_schema
    e persistência real dos insights pedagógicos no PostgreSQL.
    """
    # 1. Arrange: Professor cria sala e matricula o aluno
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Algoritmos - Teste Live IA"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Professor cadastra atividade de código com rubrica formal
    assignment_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Two Sum O(n)",
            "description": "Dado um array de inteiros e um valor alvo, retorne os índices dos dois números cuja soma seja igual ao alvo.",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "max_grade": 10.0,
                "languages": [{"name": "python3"}],
                "rubrics": "Solução deve possuir complexidade de tempo O(n) utilizando hash map e tratar casos de borda com arrays pequenos.",
                "test_cases": [
                    {
                        "id": 1,
                        "input": "[2, 7, 11, 15], target=9",
                        "expected_output": "[0, 1]",
                    },
                ],
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assignment_res.status_code == 201
    assignment_id = assignment_res.json()["id"]

    # 3. Aluno submete código em Python real
    student_code = """
def two_sum(nums: list[int], target: int) -> list[int]:
    seen: dict[int, int] = {}
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []
"""

    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": student_code}},
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    submit_data = submit_res.json()
    assert submit_data["status"] == "pending"

    # 4. BackgroundTask executou a chamada HTTPS real à API de IA.
    # Consulta o banco de dados relacional para validar o resultado da inferência real
    stmt = (
        select(Submission)
        .options(selectinload(Submission.ai_insight))
        .where(
            Submission.assignment_id == assignment_id,
            Submission.student_id == tenant.student.user.id,
        )
    )
    db_sub = (await db_session.execute(stmt)).scalar_one()

    # Validações estritas do resultado retornado pelo provedor de IA
    assert db_sub.status == SubmissionStatus.AWAITING_REVIEW
    assert db_sub.ai_insight is not None
    assert db_sub.ai_insight.status == "completed"
    assert db_sub.ai_insight.error_message is None

    suggested_grade = float(db_sub.ai_insight.suggested_grade or 0.0)
    assert 0.0 <= suggested_grade <= 10.0
    assert len(db_sub.ai_insight.strengths) >= 1
    assert isinstance(db_sub.ai_insight.reasoning, str)
    assert len(db_sub.ai_insight.reasoning) >= 15

    # Feedback para visualização no log de execução
    print(
        f"\n[AI LIVE SUCCESS] Provedor: {settings.AI_PROVIDER} | Modelo: {settings.AI_MODEL}"
    )
    print(f"[AI LIVE SUCCESS] Nota Sugerida: {suggested_grade}/10.0")
    print(f"[AI LIVE SUCCESS] Pontos Fortes: {db_sub.ai_insight.strengths}")
    print(f"[AI LIVE SUCCESS] Pontos a Melhorar: {db_sub.ai_insight.improvements}")
    print(f"[AI LIVE SUCCESS] Parecer: {db_sub.ai_insight.reasoning}")
