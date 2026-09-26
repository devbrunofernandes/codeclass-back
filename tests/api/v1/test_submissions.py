import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import (
    SubmissionStatus,
)
from app.models.submission import Submission
from tests.conftest import TenantContext

# --- 1. Testes de Submissão (POST /assignments/{assignment_id}/submissions) ---


@pytest.mark.asyncio
async def test_submit_code_assignment_when_enrolled_student_should_create_201(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "def binary_search(arr, target):\n    return 0\n",
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["assignment_id"] == str(assignment_without_submissions.id)
    assert data["student_id"] == str(tenant.student.user.id)
    assert data["status"] == "pending"
    assert "ai_insights" not in data
    assert "ai_insight" not in data


@pytest.mark.asyncio
async def test_submit_objective_questionnaire_with_immediate_policy_should_grade_and_publish_201(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    objective_questionnaire_assignment: Assignment,
):
    # Envia respostas onde a questão 1 está correta ('b') e a questão 2 está errada ('a')
    payload = {
        "content": {
            "answers": [
                {"question_id": 1, "selected_option_id": "b"},
                {"question_id": 2, "selected_option_id": "a"},
            ]
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{objective_questionnaire_assignment.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    # Acertou 1 de 2 questões de 5 pontos cada -> nota 5.00
    assert float(data["grade"]) == 5.0
    assert data["status"] == "published"
    assert "ai_insights" not in data


@pytest.mark.asyncio
async def test_submit_objective_questionnaire_with_on_review_policy_should_retain_grade_201(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    objective_questionnaire_on_review: Assignment,
):
    payload = {
        "content": {
            "answers": [
                {"question_id": 1, "selected_option_id": "a"},
            ]
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{objective_questionnaire_on_review.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    # Política ON_REVIEW retém a liberação para o estudante
    assert data["status"] == "awaiting_review"
    assert data["grade"] is None


@pytest.mark.asyncio
async def test_submit_when_deadline_passed_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    past_deadline_code_assignment: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "print(1)",
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{past_deadline_code_assignment.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "prazo" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_when_not_enrolled_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # tenant.other_student não está matriculado na sala
    payload = {
        "content": {
            "language": "python3",
            "code": "print('hacker')",
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.other_student.auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_when_teacher_calls_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "print(1)",
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_submit_when_already_submitted_active_should_return_409(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
):
    # assignment_with_submissions já possui uma submissão ativa do aluno
    payload = {"content": {"answers": [{"question_id": 1, "selected_option_id": "a"}]}}

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 409
    assert "já possui" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_when_unsupported_language_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    # A tarefa suporta apenas python3
    payload = {
        "content": {
            "language": "rust",
            "code": "fn main() {}",
        }
    }

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "linguagem" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_when_assignment_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.post(
        f"/api/v1/assignments/{uuid.uuid4()}/submissions",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_when_other_org_assignment_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_tenant,
    classroom: Classroom,
    create_assignment,
):
    other_tenant = await create_tenant("Outra Instituição")
    other_assignment = await create_assignment(classroom=classroom)

    response = await async_client.post(
        f"/api/v1/assignments/{other_assignment.id}/submissions",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=other_tenant.student.auth_headers,
    )

    assert response.status_code in [403, 404]


# --- 2. Testes de Desfazer Entrega (POST /assignments/{assignment_id}/submissions/unsubmit) ---


@pytest.mark.asyncio
async def test_unsubmit_when_active_and_within_deadline_should_succeed_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "draft"
    assert "answers" in data["content"]


@pytest.mark.asyncio
async def test_unsubmit_when_already_in_draft_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
    db_session: AsyncSession,
):
    # Coloca previamente a submissão em DRAFT
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200

    # Segunda tentativa deve dar 400
    retry_response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert retry_response.status_code == 400
    assert "rascunho" in retry_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unsubmit_when_already_published_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
    db_session: AsyncSession,
):
    # Simula que a submissão foi avaliada e publicada
    from sqlalchemy import select

    stmt = select(Submission).where(
        Submission.assignment_id == assignment_with_submissions.id,
        Submission.student_id == tenant.student.user.id,
    )
    sub = (await db_session.execute(stmt)).scalar_one()
    sub.status = SubmissionStatus.PUBLISHED
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert (
        "publicada" in response.json()["detail"].lower()
        or "avaliada" in response.json()["detail"].lower()
    )


@pytest.mark.asyncio
async def test_unsubmit_when_deadline_passed_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
    db_session: AsyncSession,
):
    # Expira o prazo da tarefa
    assignment_with_submissions.deadline = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 400
    assert "prazo" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unsubmit_when_no_submission_exists_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resubmit_draft_submission_should_succeed_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    # 1. Faz unsubmit para transitar para DRAFT
    await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    # 2. Reenvia a submissão alterada
    payload = {"content": {"answers": [{"question_id": 1, "selected_option_id": "a"}]}}
    resubmit_resp = await async_client.post(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )

    assert resubmit_resp.status_code in [200, 201]
    assert resubmit_resp.json()["status"] in ["pending", "awaiting_review", "published"]


# --- 3. Testes de Consulta da Própria Submissão (GET /assignments/{assignment_id}/submissions/me) ---


@pytest.mark.asyncio
async def test_get_my_submission_when_exists_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions/me",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["student_id"] == str(tenant.student.user.id)
    assert data["assignment_id"] == str(assignment_with_submissions.id)
    assert "ai_insights" not in data


@pytest.mark.asyncio
async def test_get_my_submission_when_none_exists_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/me",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 404


# --- 4. Testes de Matriz Obrigatória de Status Codes (401, 422 e Incompatibilidade) ---


@pytest.mark.asyncio
async def test_submissions_endpoints_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    assignment_without_submissions: Assignment,
):
    # POST /submissions sem auth
    r1 = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json={"content": {"language": "python3", "code": "pass"}},
    )
    assert r1.status_code == 401

    # POST /unsubmit sem auth
    r2 = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/unsubmit",
    )
    assert r2.status_code == 401

    # GET /submissions/me sem auth
    r3 = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/me",
    )
    assert r3.status_code == 401


@pytest.mark.asyncio
async def test_submit_when_empty_or_corrupt_payload_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    # Payload vazio
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json={},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_when_duplicate_question_ids_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    objective_questionnaire_assignment: Assignment,
):
    payload = {
        "content": {
            "answers": [
                {"question_id": 1, "selected_option_id": "b"},
                {"question_id": 1, "selected_option_id": "b"},  # Duplicada
            ]
        }
    }
    response = await async_client.post(
        f"/api/v1/assignments/{objective_questionnaire_assignment.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 422
    assert "mais de uma vez" in str(response.json())


@pytest.mark.asyncio
async def test_submit_code_payload_to_questionnaire_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    objective_questionnaire_assignment: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "print(1)",
        }
    }
    response = await async_client.post(
        f"/api/v1/assignments/{objective_questionnaire_assignment.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400
    assert "questionário" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_questionnaire_payload_to_code_assignment_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    payload = {"content": {"answers": [{"question_id": 1, "selected_option_id": "a"}]}}
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400
    assert "código" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_submit_mixed_questionnaire_should_return_201_pending(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    mixed_questionnaire_assignment: Assignment,
):
    payload = {
        "content": {
            "answers": [
                {"question_id": 1, "selected_option_id": "b"},
                {
                    "question_id": 2,
                    "text_answer": "Usa listas encadeadas em cada posição para colisões.",
                },
            ]
        }
    }
    response = await async_client.post(
        f"/api/v1/assignments/{mixed_questionnaire_assignment.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["grade"] is None


@pytest.mark.asyncio
async def test_submit_draft_resubmission_when_identical_should_return_201_awaiting_review(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "def solution(): return 42\n",
        }
    }
    # 1. Envio inicial -> 201 pending
    res1 = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert res1.status_code == 201

    # 2. Desfaz entrega -> 200 draft
    unsub_res = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert unsub_res.status_code == 200
    assert unsub_res.json()["status"] == "draft"

    # 3. Reenvio com conteúdo IDÊNTICO -> 201 awaiting_review direto (zero chamada à IA)
    res2 = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert res2.status_code == 201
    assert res2.json()["status"] == "awaiting_review"


@pytest.mark.asyncio
async def test_submit_draft_resubmission_when_modified_should_return_201_pending(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    initial_payload = {
        "content": {
            "language": "python3",
            "code": "def solution(): return 1\n",
        }
    }
    # 1. Envio inicial
    await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=initial_payload,
        headers=tenant.student.auth_headers,
    )

    # 2. Desfaz entrega -> draft
    await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )

    # 3. Reenvio com conteúdo MODIFICADO -> 201 pending (aciona nova inferência)
    modified_payload = {
        "content": {
            "language": "python3",
            "code": "def solution(): return 2\n",
        }
    }
    res = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json=modified_payload,
        headers=tenant.student.auth_headers,
    )
    assert res.status_code == 201
    assert res.json()["status"] == "pending"
