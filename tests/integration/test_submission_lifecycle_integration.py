from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import SubmissionStatus
from app.models.submission import Submission, SubmissionEvaluation
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_full_submission_lifecycle_code_and_unsubmit_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    """Jornada E2E: criação de turma, atividade de código, submissão pelo aluno,

    consulta sanitizada, unsubmit no prazo, reenvio com sucesso e proteção contra duplicação.
    """
    # 1. Arrange: Professor cria uma sala de aula e matricula o aluno
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Algoritmos E2E"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    enroll_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    assert enroll_res.status_code == 201

    # 2. Professor cadastra atividade de código
    assignment_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Busca em Largura",
            "description": "Implemente BFS iterativo",
            "type": "code",
            "release_policy": "on_review",
            "deadline": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "config": {
                "languages": [{"name": "python3", "starter_code": "def bfs(): pass"}],
                "time_limit_sec": 2.0,
                "memory_limit_mb": 128,
                "rubric": "Avaliar complexidade O(V+E)",
                "test_cases": [
                    {"id": 1, "input": "graph\n", "expected_output": "bfs\n"}
                ],
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assignment_res.status_code == 201
    assignment_id = assignment_res.json()["id"]

    # 3. Aluno realiza a submissão inicial de código
    initial_code = "def bfs(graph, start):\n    return [start]\n"
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": initial_code}},
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    submission_data = submit_res.json()
    assert submission_data["status"] == "pending"
    assert submission_data["content"]["code"] == initial_code
    assert "ai_insights" not in submission_data
    assert "ai_insight" not in submission_data

    # 4. Aluno consulta a própria entrega via GET /submissions/me (processada pelo worker de IA em background)
    me_res = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/me",
        headers=tenant.student.auth_headers,
    )
    assert me_res.status_code == 200
    assert me_res.json()["id"] == submission_data["id"]
    assert me_res.json()["status"] == "awaiting_review"

    # 5. Tentativa de segunda submissão ativa deve falhar com 409 Conflict (RF21)
    conflict_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": "def bfs(): return []"}},
        headers=tenant.student.auth_headers,
    )
    assert conflict_res.status_code == 409
    assert "já possui" in conflict_res.json()["detail"].lower()

    # 6. Aluno decide desfazer a entrega (Unsubmit) para ajustar o algoritmo
    unsubmit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsubmit_res.status_code == 200
    unsubmit_data = unsubmit_res.json()
    assert unsubmit_data["status"] == "draft"
    # O conteúdo anterior continua integralmente preservado para reedição
    assert unsubmit_data["content"]["code"] == initial_code

    # 7. Aluno reenvia o código corrigido a partir do estado DRAFT
    refined_code = "def bfs(graph, start):\n    queue = [start]\n    return queue\n"
    resubmit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": refined_code}},
        headers=tenant.student.auth_headers,
    )
    assert resubmit_res.status_code == 201
    resubmit_data = resubmit_res.json()
    assert resubmit_data["status"] == "pending"
    assert resubmit_data["content"]["code"] == refined_code

    # 8. Valida o estado diretamente no banco de dados relacional (processado pelo worker de IA em background)
    stmt = (
        select(Submission)
        .options(selectinload(Submission.ai_insight))
        .where(
            Submission.assignment_id == assignment_id,
            Submission.student_id == tenant.student.user.id,
        )
    )
    db_sub = (await db_session.execute(stmt)).scalar_one()
    assert db_sub.status == SubmissionStatus.AWAITING_REVIEW
    assert db_sub.content["code"] == refined_code
    assert db_sub.ai_insight is not None
    assert db_sub.ai_insight.status == "completed"


@pytest.mark.asyncio
async def test_full_objective_questionnaire_auto_grading_lifecycle_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    """Jornada E2E: questionário 100% objetivo com liberação imediata,

    cálculo matemático de nota no PostgreSQL, criação de avaliação e bloqueio de unsubmit.
    """
    # 1. Arrange: Professor cria sala e matricula o aluno
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Teoria da Computação E2E"},
        headers=tenant.teacher.auth_headers,
    )
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Professor cria questionário objetivo com liberação imediata (IMMEDIATE)
    assignment_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Quiz sobre Autômatos",
            "description": "Perguntas de múltipla escolha",
            "type": "questionnaire",
            "release_policy": "immediate",
            "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            "config": {
                "questions": [
                    {
                        "id": 1,
                        "type": "choice",
                        "points": 4.0,
                        "statement": "Linguagens regulares são reconhecidas por AFD?",
                        "options": [
                            {"id": "a", "text": "Sim"},
                            {"id": "b", "text": "Não"},
                        ],
                        "correct_option_id": "a",
                    },
                    {
                        "id": 2,
                        "type": "choice",
                        "points": 6.0,
                        "statement": "O problema da parada é decidível?",
                        "options": [
                            {"id": "a", "text": "Sim"},
                            {"id": "b", "text": "Não"},
                        ],
                        "correct_option_id": "b",
                    },
                ]
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assignment_id = assignment_res.json()["id"]

    # 3. Aluno envia respostas (Questão 1: 'a' [Certa], Questão 2: 'a' [Errada])
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={
            "content": {
                "answers": [
                    {"question_id": 1, "selected_option_id": "a"},
                    {"question_id": 2, "selected_option_id": "a"},
                ]
            }
        },
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    submit_data = submit_res.json()

    # Como a política é IMMEDIATE, transita diretamente para PUBLISHED com a nota atribuída
    assert submit_data["status"] == "published"
    assert float(submit_data["grade"]) == 4.0

    # 4. Verifica se a avaliação formal foi criada automaticamente no banco
    stmt_eval = select(SubmissionEvaluation).where(
        SubmissionEvaluation.submission_id == submit_data["id"]
    )
    db_eval = (await db_session.execute(stmt_eval)).scalar_one()
    assert float(db_eval.grade) == 4.0
    assert db_eval.general_feedback == "Correção automática"
    assert len(db_eval.detailed_scores["questions_evaluation"]) == 2

    # 5. Tentativa de unsubmit deve ser bloqueada com 400 (atividade já avaliada e publicada)
    unsubmit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsubmit_res.status_code == 400
    assert (
        "publicada" in unsubmit_res.json()["detail"].lower()
        or "avaliada" in unsubmit_res.json()["detail"].lower()
    )


@pytest.mark.asyncio
async def test_ai_background_processing_failure_fallback_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
    mock_ai_service: AsyncMock,
):
    """Jornada E2E de resiliência: falha do Gemini não congela a submissão em PENDING,

    gravando ai_insight com status='failed' e transitando a entrega para AWAITING_REVIEW (HLD 9.2).
    """
    # 1. Arrange: Simula falha catastrófica da API do Gemini (timeout/rate limit)
    mock_ai_service.side_effect = RuntimeError("Google Gemini API timeout error (504)")

    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Resiliência IA"},
        headers=tenant.teacher.auth_headers,
    )
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    assignment_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Merge Sort Resiliente",
            "description": "Implemente merge sort",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "languages": [{"name": "python3"}],
                "max_grade": 10.0,
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assignment_id = assignment_res.json()["id"]

    # 2. Aluno submete o código
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={
            "content": {
                "language": "python3",
                "code": "def mergesort(arr): return sorted(arr)",
            }
        },
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    assert submit_res.json()["status"] == "pending"

    # 3. Valida no banco que a resiliência funcionou: transita para awaiting_review com status='failed'
    stmt = (
        select(Submission)
        .options(selectinload(Submission.ai_insight))
        .where(
            Submission.assignment_id == assignment_id,
            Submission.student_id == tenant.student.user.id,
        )
    )
    db_sub = (await db_session.execute(stmt)).scalar_one()
    assert db_sub.status == SubmissionStatus.AWAITING_REVIEW
    assert db_sub.ai_insight is not None
    assert db_sub.ai_insight.status == "failed"
    assert "timeout error" in (db_sub.ai_insight.error_message or "")


@pytest.mark.asyncio
async def test_draft_resubmission_idempotency_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
    mock_ai_service: AsyncMock,
):
    """Jornada E2E de idempotência: reenvio de rascunho com código idêntico NÃO chama a IA novamente.

    Reenvio com código alterado aciona nova inferência.
    """
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Idempotência"},
        headers=tenant.teacher.auth_headers,
    )
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    assignment_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Quick Sort Idempotente",
            "description": "Implemente quicksort",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "languages": [{"name": "python3"}],
                "max_grade": 10.0,
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assignment_id = assignment_res.json()["id"]

    code = "def quicksort(arr): return arr"

    # 1. Envio inicial
    res1 = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": code}},
        headers=tenant.student.auth_headers,
    )
    assert res1.status_code == 201
    assert mock_ai_service.call_count == 1

    # 2. Desfaz entrega -> DRAFT
    unsubmit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsubmit_res.status_code == 200
    assert unsubmit_res.json()["status"] == "draft"

    # 3. Reenvia exatamente o mesmo código -> NÃO deve chamar a IA (reaproveita insight anterior)
    res2 = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": code}},
        headers=tenant.student.auth_headers,
    )
    assert res2.status_code == 201
    assert res2.json()["status"] == "awaiting_review"
    assert mock_ai_service.call_count == 1  # Continua 1! Zero chamadas redundantes

    # 4. Desfaz entrega novamente
    await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    # 5. Reenvia código MODIFICADO -> Deve disparar nova análise de IA
    new_code = "def quicksort(arr): return sorted(arr)"
    res3 = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": new_code}},
        headers=tenant.student.auth_headers,
    )
    assert res3.status_code == 201
    assert res3.json()["status"] == "pending"
    assert mock_ai_service.call_count == 2  # Disparou nova inferência!
