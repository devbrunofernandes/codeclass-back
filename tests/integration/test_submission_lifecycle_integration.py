from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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

    # 4. Aluno consulta a própria entrega via GET /submissions/me
    me_res = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/me",
        headers=tenant.student.auth_headers,
    )
    assert me_res.status_code == 200
    assert me_res.json()["id"] == submission_data["id"]
    assert me_res.json()["status"] == "pending"

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

    # 8. Valida o estado diretamente no banco de dados relacional
    stmt = select(Submission).where(
        Submission.assignment_id == assignment_id,
        Submission.student_id == tenant.student.user.id,
    )
    db_sub = (await db_session.execute(stmt)).scalar_one()
    assert db_sub.status == SubmissionStatus.PENDING
    assert db_sub.content["code"] == refined_code


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
