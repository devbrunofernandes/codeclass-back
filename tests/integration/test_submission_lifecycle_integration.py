import uuid
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

    # 4. Aluno lista suas submissões e consulta os detalhes da entrega
    list_res = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions",
        headers=tenant.student.auth_headers,
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["id"] == submission_data["id"]

    detail_res = await async_client.get(
        f"/api/v1/submissions/{submission_data['id']}",
        headers=tenant.student.auth_headers,
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == submission_data["id"]
    assert detail_res.json()["status"] == "awaiting_review"

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


@pytest.mark.asyncio
async def test_full_teacher_evaluation_and_student_feedback_lifecycle_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    """Jornada E2E completa de avaliação docente e liberação de notas:

    Aluno submete -> IA analisa em background -> Professor lista pendentes e consulta insights ->
    Professor salva rascunho de nota retida (publish=False) -> Aluno tem nota bloqueada ->
    Professor publica nota formal (publish=True) -> Aluno consulta avaliação com nota oficial ->
    Aluno é impedido de desfazer entrega já avaliada.
    """
    # 1. Turma e matrícula
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Avaliação Formal E2E"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Professor cria atividade de código
    assign_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Merge Sort Formal",
            "description": "Implemente merge sort com recursão",
            "type": "code",
            "release_policy": "on_review",
            "config": {
                "languages": [{"name": "python3"}],
                "max_grade": 10.0,
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assign_res.status_code == 201
    assignment_id = assign_res.json()["id"]

    # 3. Aluno envia a submissão formal de código
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
    sub_id = submit_res.json()["id"]

    # 4. Professor lista submissões filtradas por status awaiting_review
    list_res = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions?status=awaiting_review",
        headers=tenant.teacher.auth_headers,
    )
    assert list_res.status_code == 200
    submissions_list = list_res.json()
    assert len(submissions_list) == 1
    assert submissions_list[0]["id"] == sub_id
    assert submissions_list[0]["ai_insight_status"] == "completed"

    # 5. Professor abre a submissão detalhada com parecer confidencial da IA
    detail_res = await async_client.get(
        f"/api/v1/submissions/{sub_id}",
        headers=tenant.teacher.auth_headers,
    )
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["ai_insight"] is not None
    assert detail_data["ai_insight"]["status"] == "completed"
    assert detail_data["ai_insight"]["suggested_grade"] is not None

    # 6. Professor registra avaliação em rascunho com retenção (publish=False)
    draft_eval_res = await async_client.put(
        f"/api/v1/submissions/{sub_id}/evaluation",
        json={
            "grade": 9.5,
            "general_feedback": "Excelente lógica. Falta apenas documentar.",
            "detailed_scores": {"code_quality": 4.5, "correctness": 5.0},
            "publish": False,
        },
        headers=tenant.teacher.auth_headers,
    )
    assert draft_eval_res.status_code == 200

    # 7. Aluno consulta GET /submissions/{id} -> nota continua retida (None), status awaiting_review e evaluation oculta
    detail_res = await async_client.get(
        f"/api/v1/submissions/{sub_id}",
        headers=tenant.student.auth_headers,
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["grade"] is None
    assert detail_res.json()["status"] == "awaiting_review"
    assert detail_res.json()["evaluation"] is None

    # 8. Aluno tenta consultar GET /submissions/{id}/evaluation antes da publicação -> 403 Forbidden
    student_eval_res = await async_client.get(
        f"/api/v1/submissions/{sub_id}/evaluation",
        headers=tenant.student.auth_headers,
    )
    assert student_eval_res.status_code == 403

    # 9. Professor finaliza e publica a avaliação (publish=True)
    publish_eval_res = await async_client.put(
        f"/api/v1/submissions/{sub_id}/evaluation",
        json={
            "grade": 9.5,
            "general_feedback": "Excelente lógica. Parabéns!",
            "detailed_scores": {"code_quality": 4.5, "correctness": 5.0},
            "publish": True,
        },
        headers=tenant.teacher.auth_headers,
    )
    assert publish_eval_res.status_code == 200

    # 10. Aluno consulta novamente /submissions/{id} -> nota oficial publicada, status published e avaliação liberada
    detail_res_after = await async_client.get(
        f"/api/v1/submissions/{sub_id}",
        headers=tenant.student.auth_headers,
    )
    assert detail_res_after.status_code == 200
    assert float(detail_res_after.json()["grade"]) == 9.5
    assert detail_res_after.json()["status"] == "published"
    assert detail_res_after.json()["evaluation"] is not None
    assert float(detail_res_after.json()["evaluation"]["grade"]) == 9.5

    # 11. Aluno consulta formalmente a avaliação -> 200 OK com parecer do professor
    eval_released_res = await async_client.get(
        f"/api/v1/submissions/{sub_id}/evaluation",
        headers=tenant.student.auth_headers,
    )
    assert eval_released_res.status_code == 200
    assert float(eval_released_res.json()["grade"]) == 9.5
    assert eval_released_res.json()["general_feedback"] == "Excelente lógica. Parabéns!"

    # 12. Aluno tenta desfazer a entrega (Unsubmit) após publicação -> deve ser bloqueado com 400 Bad Request
    unsubmit_blocked = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsubmit_blocked.status_code == 400
    assert "já avaliada" in unsubmit_blocked.json()["detail"].lower()


@pytest.mark.asyncio
async def test_batch_evaluation_release_lifecycle_integration_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    """Jornada completa E2E: dois alunos entregam, professor avalia em rascunho e publica em lote."""
    # 1. Configuração da sala e atividade dissertativa/código
    classroom_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={
            "name": "Turma de Estruturas de Dados Batch",
            "description": "Teste Batch",
        },
        headers=tenant.teacher.auth_headers,
    )
    assert classroom_res.status_code == 201
    class_id = classroom_res.json()["id"]

    # Matricula o aluno 1 e aluno 2
    r_enroll1 = await async_client.post(
        f"/api/v1/classrooms/{class_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    assert r_enroll1.status_code == 201

    r_enroll2 = await async_client.post(
        f"/api/v1/classrooms/{class_id}/students",
        json={"student_id": str(tenant.other_student.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    assert r_enroll2.status_code == 201

    assign_res = await async_client.post(
        f"/api/v1/classrooms/{class_id}/assignments",
        json={
            "title": "Árvores Binárias de Busca",
            "description": "Implemente a inserção balanceada",
            "type": "code",
            "release_policy": "on_review",
            "deadline": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "config": {
                "languages": [{"name": "python3"}],
                "rubric": "Corretude do algoritmo",
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assign_res.status_code == 201
    assignment_id = assign_res.json()["id"]

    # 2. Aluno 1 submete
    sub1_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": "# Aluno 1 code"}},
        headers=tenant.student.auth_headers,
    )
    assert sub1_res.status_code == 201
    sub1_id = sub1_res.json()["id"]

    # 3. Aluno 2 submete
    sub2_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": "# Aluno 2 code"}},
        headers=tenant.other_student.auth_headers,
    )
    assert sub2_res.status_code == 201
    sub2_id = sub2_res.json()["id"]

    # 4. Professor avalia ambos mantendo em rascunho (publish=False)
    eval1 = await async_client.put(
        f"/api/v1/submissions/{sub1_id}/evaluation",
        json={"grade": 8.0, "general_feedback": "Bom trabalho", "publish": False},
        headers=tenant.teacher.auth_headers,
    )
    assert eval1.status_code == 200

    eval2 = await async_client.put(
        f"/api/v1/submissions/{sub2_id}/evaluation",
        json={"grade": 9.5, "general_feedback": "Excelente solução", "publish": False},
        headers=tenant.teacher.auth_headers,
    )
    assert eval2.status_code == 200

    # 5. Ambos alunos verificam que nota e avaliação estão retidas
    check1 = await async_client.get(
        f"/api/v1/submissions/{sub1_id}",
        headers=tenant.student.auth_headers,
    )
    assert check1.json()["status"] == "awaiting_review"
    assert check1.json()["grade"] is None
    assert check1.json()["evaluation"] is None

    check2 = await async_client.get(
        f"/api/v1/submissions/{sub2_id}",
        headers=tenant.other_student.auth_headers,
    )
    assert check2.json()["status"] == "awaiting_review"
    assert check2.json()["grade"] is None
    assert check2.json()["evaluation"] is None

    # 6. Professor dispara liberação em lote das correções
    batch_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/publish-evaluations",
        headers=tenant.teacher.auth_headers,
    )
    assert batch_res.status_code == 200
    assert batch_res.json()["published_count"] == 2

    # 7. Ambos alunos agora verificam que as notas e pareceres foram liberados
    final1 = await async_client.get(
        f"/api/v1/submissions/{sub1_id}",
        headers=tenant.student.auth_headers,
    )
    assert final1.json()["status"] == "published"
    assert float(final1.json()["grade"]) == 8.0
    assert final1.json()["evaluation"] is not None

    final2 = await async_client.get(
        f"/api/v1/submissions/{sub2_id}",
        headers=tenant.other_student.auth_headers,
    )
    assert final2.json()["status"] == "published"
    assert float(final2.json()["grade"]) == 9.5
    assert final2.json()["evaluation"] is not None


@pytest.mark.asyncio
async def test_selective_batch_evaluation_release_and_stats_lifecycle_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    """Jornada E2E completa: métricas executivas da tarefa, busca/filtro e liberação seletiva em lote."""
    # 1. Cria turma e matricula 2 alunos
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma com Métricas e Lote Seletivo"},
        headers=tenant.teacher.auth_headers,
    )
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.other_student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Cria atividade
    assign_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Árvores AVL e Balanceamento",
            "description": "Implemente a rotação dupla",
            "type": "code",
            "release_policy": "on_review",
            "deadline": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            "config": {
                "languages": [{"name": "python3"}],
                "rubric": "Corretude do algoritmo",
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assignment_id = assign_res.json()["id"]

    # 3. Estatísticas iniciais: 2 matriculados, 0 submissões
    stats_res0 = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    assert stats_res0.status_code == 200
    s0 = stats_res0.json()
    assert s0["total_enrolled"] == 2
    assert s0["total_submissions"] == 0

    # 4. Ambos alunos submetem
    sub1_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": "# AVL Aluno 1"}},
        headers=tenant.student.auth_headers,
    )
    sub1_id = sub1_res.json()["id"]

    sub2_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": "# AVL Aluno 2"}},
        headers=tenant.other_student.auth_headers,
    )
    sub2_id = sub2_res.json()["id"]

    # 5. Estatísticas pós-submissões: 2 awaiting_review (ainda sem avaliação docente)
    stats_res1 = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    s1 = stats_res1.json()
    assert s1["total_submissions"] == 2
    assert s1["awaiting_review"] == 2
    assert s1["ready_to_publish"] == 0

    # 6. Filtro por busca de texto (termo único 'Other' do second student)
    list_q = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions?q=Other",
        headers=tenant.teacher.auth_headers,
    )
    assert len(list_q.json()) == 1
    assert list_q.json()[0]["id"] == sub2_id

    # 7. Professor avalia apenas Aluno 1 em rascunho
    await async_client.put(
        f"/api/v1/submissions/{sub1_id}/evaluation",
        json={
            "grade": 8.0,
            "general_feedback": "Ótimo balanceamento",
            "publish": False,
        },
        headers=tenant.teacher.auth_headers,
    )

    # 8. Estatísticas: 1 awaiting_review, 1 ready_to_publish
    stats_res2 = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    s2 = stats_res2.json()
    assert s2["awaiting_review"] == 1
    assert s2["ready_to_publish"] == 1
    assert s2["published"] == 0

    # 9. Professor libera seletivamente APENAS a avaliação de sub1
    batch_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/publish-evaluations",
        json={"submission_ids": [sub1_id]},
        headers=tenant.teacher.auth_headers,
    )
    assert batch_res.status_code == 200
    assert batch_res.json()["published_count"] == 1

    # 10. Estatísticas finais: 1 publicado, 1 aguardando revisão, nota média 8.0
    stats_res3 = await async_client.get(
        f"/api/v1/assignments/{assignment_id}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    s3 = stats_res3.json()
    assert s3["published"] == 1
    assert s3["ready_to_publish"] == 0
    assert s3["awaiting_review"] == 1
    assert float(s3["average_grade"]) == 8.0


@pytest.mark.asyncio
async def test_submission_draft_autosave_lifecycle_and_ai_retry_e2e(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    """Jornada E2E completa de auto-save de rascunhos e reprocessamento de IA:

    1. Criação de sala e tarefa pelo docente
    2. Auto-save de rascunho parcial pelo aluno (status=draft)
    3. Atualização incremental do rascunho (status=draft)
    4. Submissão formal (status=pending)
    5. Bloqueio de auto-save durante entrega formal ativa (400)
    6. Desfazer entrega (unsubmit -> status=draft)
    7. Novo auto-save após unsubmit (status=draft)
    8. Reenvio formal
    9. Simulação de falha na inferência de IA (status=failed)
    10. Docente aciona reprocessamento sob demanda (POST /retry-ai -> 200)
    11. Avaliação e publicação docente
    12. Bloqueio de auto-save e retry-ai após publicação
    """
    # 1. Cria sala de aula e matricula aluno
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Rascunhos e IA E2E"},
        headers=tenant.teacher.auth_headers,
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Cria atividade de código
    assign_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json={
            "title": "Merge Sort",
            "description": "Implemente Merge Sort",
            "type": "code",
            "release_policy": "on_review",
            "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
            "config": {
                "languages": [
                    {"name": "python3", "starter_code": "def mergesort(): pass"}
                ],
                "time_limit_sec": 2.0,
                "memory_limit_mb": 128,
                "rubric": "Avaliar estabilidade e divisão e conquista",
                "test_cases": [
                    {"id": 1, "input": "3 1 2\n", "expected_output": "1 2 3\n"}
                ],
            },
        },
        headers=tenant.teacher.auth_headers,
    )
    assert assign_res.status_code == 201
    assignment_id = assign_res.json()["id"]

    # 3. Aluno salva rascunho inicial incompleto
    draft1_res = await async_client.put(
        f"/api/v1/assignments/{assignment_id}/submissions/draft",
        json={
            "content": {
                "language": "python3",
                "code": "def mergesort(arr):\n    # TODO",
            }
        },
        headers=tenant.student.auth_headers,
    )
    assert draft1_res.status_code == 200
    assert draft1_res.json()["status"] == "draft"
    submission_id = draft1_res.json()["id"]

    # 4. Aluno atualiza rascunho com código funcional
    code_v2 = "def mergesort(arr):\n    if len(arr) <= 1: return arr\n    return sorted(arr)\n"
    draft2_res = await async_client.put(
        f"/api/v1/assignments/{assignment_id}/submissions/draft",
        json={"content": {"language": "python3", "code": code_v2}},
        headers=tenant.student.auth_headers,
    )
    assert draft2_res.status_code == 200
    assert draft2_res.json()["id"] == submission_id
    assert draft2_res.json()["content"]["code"] == code_v2

    # 5. Aluno realiza entrega formal
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": code_v2}},
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    assert submit_res.json()["status"] == "pending"

    # 6. Tentativa de auto-save durante entrega ativa deve retornar 400
    block_draft = await async_client.put(
        f"/api/v1/assignments/{assignment_id}/submissions/draft",
        json={"content": {"language": "python3", "code": "def hack(): pass"}},
        headers=tenant.student.auth_headers,
    )
    assert block_draft.status_code == 400
    assert "desfaça a entrega primeiro" in block_draft.json()["detail"].lower()

    # 7. Aluno desfaz entrega formal (unsubmit)
    unsub_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsub_res.status_code == 200
    assert unsub_res.json()["status"] == "draft"

    # 8. Aluno pode salvar rascunho novamente
    code_v3 = "def mergesort(arr):\n    return sorted(arr)\n"
    draft3_res = await async_client.put(
        f"/api/v1/assignments/{assignment_id}/submissions/draft",
        json={"content": {"language": "python3", "code": code_v3}},
        headers=tenant.student.auth_headers,
    )
    assert draft3_res.status_code == 200
    assert draft3_res.json()["status"] == "draft"

    # 9. Reenvio formal com novo código
    resubmit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_id}/submissions",
        json={"content": {"language": "python3", "code": code_v3}},
        headers=tenant.student.auth_headers,
    )
    assert resubmit_res.status_code == 201

    # 10. Simula falha transitória de IA no PostgreSQL
    sub_stmt = (
        select(Submission)
        .options(selectinload(Submission.ai_insight))
        .where(Submission.id == uuid.UUID(submission_id))
    )
    sub_db = (await db_session.execute(sub_stmt)).scalar_one()
    sub_db.status = SubmissionStatus.AWAITING_REVIEW
    if sub_db.ai_insight:
        sub_db.ai_insight.status = "failed"
        sub_db.ai_insight.error_message = "Rate limit 429 transitório"
    await db_session.commit()

    # 11. Docente visualiza falha na consulta detalhada
    teacher_detail = await async_client.get(
        f"/api/v1/submissions/{submission_id}",
        headers=tenant.teacher.auth_headers,
    )
    assert teacher_detail.status_code == 200
    assert teacher_detail.json()["ai_insight"]["status"] == "failed"

    # 12. Docente aciona retry de IA sob demanda
    retry_res = await async_client.post(
        f"/api/v1/submissions/{submission_id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert retry_res.status_code == 200
    assert retry_res.json()["status"] == "pending"
    assert retry_res.json()["ai_insight"]["status"] == "in_progress"

    # 13. Docente avalia e publica a correção
    eval_res = await async_client.put(
        f"/api/v1/submissions/{submission_id}/evaluation",
        json={
            "grade": 9.5,
            "general_feedback": "Excelente implementação de ordenação",
            "publish": True,
        },
        headers=tenant.teacher.auth_headers,
    )
    assert eval_res.status_code == 200

    # 14. Validação final pós-publicação: auto-save e retry-ai bloqueados
    post_pub_draft = await async_client.put(
        f"/api/v1/assignments/{assignment_id}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=tenant.student.auth_headers,
    )
    assert post_pub_draft.status_code == 400

    post_pub_retry = await async_client.post(
        f"/api/v1/submissions/{submission_id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert post_pub_retry.status_code == 400
