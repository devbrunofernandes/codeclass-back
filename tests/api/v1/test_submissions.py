import uuid
from collections.abc import Awaitable, Callable
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


# --- 3. Testes de Listagem de Submissões pelo Aluno (GET /assignments/{assignment_id}/submissions) ---


@pytest.mark.asyncio
async def test_list_submissions_when_enrolled_student_should_return_200_with_own_submissions(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_with_submissions.id}/submissions",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["student"]["id"] == str(tenant.student.user.id)
    assert data[0]["assignment"]["id"] == str(assignment_with_submissions.id)
    assert "assignment_id" not in data[0]
    assert "student_id" not in data[0]
    assert "ai_insight" not in data[0]
    assert "ai_insight_status" not in data[0]


@pytest.mark.asyncio
async def test_list_submissions_when_student_has_no_submissions_should_return_empty_list(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=tenant.student.auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == []


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

    # GET /submissions sem auth
    r3 = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
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


# --- 4. Listagem Docente de Submissões (GET /assignments/{assignment_id}/submissions) ---


@pytest.mark.asyncio
async def test_list_submissions_when_teacher_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    item = next(s for s in data if s["id"] == str(submission_awaiting_review.id))
    assert item["assignment"]["id"] == str(assignment_without_submissions.id)
    assert "assignment_id" not in item
    assert item["status"] == "awaiting_review"
    assert item["ai_insight_status"] == "completed"
    assert "student" in item
    assert "student_id" not in item
    assert item["student"]["full_name"] == tenant.student.user.full_name


@pytest.mark.asyncio
async def test_list_submissions_with_status_filter_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Filtro com status que existe
    res1 = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions?status=awaiting_review",
        headers=tenant.teacher.auth_headers,
    )
    assert res1.status_code == 200
    assert len(res1.json()) >= 1

    # Filtro com status que não existe para essa submissão
    res2 = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions?status=published",
        headers=tenant.teacher.auth_headers,
    )
    assert res2.status_code == 200
    assert len(res2.json()) == 0


@pytest.mark.asyncio
async def test_list_submissions_when_admin_or_owner_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Admin
    res_admin = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 200

    # Owner
    res_owner = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 200


@pytest.mark.asyncio
async def test_list_submissions_when_unenrolled_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # other_student pertence à organização, mas não está matriculado na sala da atividade
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_submissions_when_other_org_member_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    assignment_without_submissions: Assignment,
):
    other_tenant = await create_tenant("Outra Instituição de Ensino")
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_submissions_when_assignment_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.get(
        f"/api/v1/assignments/{uuid.uuid4()}/submissions",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


# --- 5. GET /submissions/{submission_id} (Detalhe da Submissão) ---


@pytest.mark.asyncio
async def test_get_submission_detail_when_teacher_should_include_ai_insight_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(submission_awaiting_review.id)
    assert "assignment_id" not in data
    assert "student_id" not in data
    assert data["assignment"]["id"] == str(submission_awaiting_review.assignment_id)
    assert data["student"]["id"] == str(submission_awaiting_review.student_id)
    assert "ai_insight" in data
    assert data["ai_insight"] is not None
    assert data["ai_insight"]["status"] == "completed"
    assert float(data["ai_insight"]["suggested_grade"]) == 8.5
    assert data["ai_insight"]["reasoning"] is not None


@pytest.mark.asyncio
async def test_get_submission_detail_when_student_author_should_be_sanitized_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(submission_awaiting_review.id)
    assert "assignment_id" not in data
    assert "student_id" not in data
    assert data["assignment"]["id"] == str(submission_awaiting_review.assignment_id)
    assert data["student"]["id"] == str(submission_awaiting_review.student_id)
    assert "content" in data
    # Aluno NÃO recebe insights confidenciais da IA (campo ausente no schema do estudante)!
    assert "ai_insight" not in data
    assert "ai_insights" not in data
    # Como ainda está awaiting_review, a avaliação não foi publicada
    assert data.get("evaluation") is None


@pytest.mark.asyncio
async def test_get_submission_detail_when_student_author_and_published_should_include_evaluation_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_published: Submission,
):
    response = await async_client.get(
        f"/api/v1/submissions/{submission_published.id}",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(submission_published.id)
    assert data["status"] == "published"
    assert "student_id" not in data
    assert data["student"]["id"] == str(submission_published.student_id)
    assert "ai_insight" not in data
    assert "ai_insights" not in data
    assert data.get("evaluation") is not None
    assert float(data["evaluation"]["grade"]) == 9.0


@pytest.mark.asyncio
async def test_get_submission_detail_when_other_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # Outro aluno da mesma organização tentando ver entrega de colega
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_submission_detail_when_other_org_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    submission_awaiting_review: Submission,
):
    other_tenant = await create_tenant("Outra Instituição de Ensino 2")
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_submission_detail_when_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.get(
        f"/api/v1/submissions/{uuid.uuid4()}",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


# --- 6. PUT /submissions/{submission_id}/evaluation (Avaliação Docente) ---


@pytest.mark.asyncio
async def test_evaluate_submission_when_teacher_and_publish_true_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    payload = {
        "grade": 9.5,
        "general_feedback": "Ótimo raciocínio na resolução do problema!",
        "detailed_scores": {
            "questions_evaluation": [
                {
                    "question_id": 1,
                    "type": "choice",
                    "awarded_points": 5.0,
                    "max_points": 5.0,
                    "is_correct": True,
                }
            ]
        },
        "publish": True,
    }

    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert float(data["grade"]) == 9.5
    assert data["general_feedback"] == "Ótimo raciocínio na resolução do problema!"
    assert data["detailed_scores"] is not None

    # Verifica se a submissão passou para published e nota foi gravada
    sub_res = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "published"
    assert float(sub_res.json()["grade"]) == 9.5


@pytest.mark.asyncio
async def test_evaluate_submission_when_publish_false_should_retain_status_awaiting_review_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    payload = {
        "grade": 8.0,
        "general_feedback": "Avaliação preliminar salva pelo docente",
        "publish": False,
    }

    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert float(data["grade"]) == 8.0

    # Verifica que submissão continua em awaiting_review e nota não foi liberada
    sub_res = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert sub_res.status_code == 200
    assert sub_res.json()["status"] == "awaiting_review"
    assert sub_res.json()["grade"] is None


@pytest.mark.asyncio
async def test_evaluate_submission_when_admin_or_owner_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    payload = {"grade": 10.0, "publish": True}

    # Admin não pode avaliar (RBAC HLD linha 111)
    res_admin = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 403

    # Owner não pode avaliar
    res_owner = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 403


@pytest.mark.asyncio
async def test_evaluate_submission_when_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    payload = {"grade": 10.0, "publish": True}
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_evaluate_submission_when_draft_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    enrolled_student: ClassroomStudent,
    create_submission,
):
    draft_sub = await create_submission(
        assignment=assignment_without_submissions,
        student_id=enrolled_student.student_id,
        status=SubmissionStatus.DRAFT,
    )
    payload = {"grade": 7.0, "publish": True}
    response = await async_client.put(
        f"/api/v1/submissions/{draft_sub.id}/evaluation",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400
    assert "rascunho" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_evaluate_submission_when_invalid_grade_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    payload = {"grade": -5.0, "publish": True}
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 422


# --- 7. GET /submissions/{submission_id}/evaluation (Consulta da Avaliação) ---


@pytest.mark.asyncio
async def test_get_evaluation_when_published_and_student_author_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_published: Submission,
):
    response = await async_client.get(
        f"/api/v1/submissions/{submission_published.id}/evaluation",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert float(data["grade"]) == 9.0
    assert data["general_feedback"] == "Excelente implementação do algoritmo!"
    assert data["detailed_scores"] is not None


@pytest.mark.asyncio
async def test_get_evaluation_when_not_published_and_student_author_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # 1. Professor avalia mas retém publicação (publish=False)
    await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 8.0, "publish": False},
        headers=tenant.teacher.auth_headers,
    )

    # 2. Aluno tenta consultar avaliação ainda não liberada
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403
    assert "publicada" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_evaluation_when_teacher_or_admin_should_return_200_even_if_not_published(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # Professor salva avaliação preliminar
    await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 7.5, "general_feedback": "Rascunho", "publish": False},
        headers=tenant.teacher.auth_headers,
    )

    # Professor consulta
    res_teacher = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        headers=tenant.teacher.auth_headers,
    )
    assert res_teacher.status_code == 200
    assert float(res_teacher.json()["grade"]) == 7.5

    # Admin consulta
    res_admin = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 200


@pytest.mark.asyncio
async def test_get_evaluation_when_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # Submissão existe mas não tem avaliação registrada
    response = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


# --- 8. Testes de 401 Unauthorized e Bloqueio de Unsubmit com Avaliação ---


@pytest.mark.asyncio
async def test_submission_and_evaluation_endpoints_when_unauthorized_should_return_401(
    async_client: AsyncClient,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # 1. GET /assignments/{id}/submissions
    res1 = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions"
    )
    assert res1.status_code == 401

    # 2. GET /submissions/{id}
    res2 = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}"
    )
    assert res2.status_code == 401

    # 3. PUT /submissions/{id}/evaluation
    res3 = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 10.0, "publish": True},
    )
    assert res3.status_code == 401

    # 4. GET /submissions/{id}/evaluation
    res4 = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation"
    )
    assert res4.status_code == 401


@pytest.mark.asyncio
async def test_unsubmit_when_preliminary_evaluation_exists_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Professor salva rascunho de avaliação (publish=False)
    await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 8.0, "publish": False},
        headers=tenant.teacher.auth_headers,
    )

    # Aluno tenta desfazer a entrega enquanto o professor já avaliou preliminarmente
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/unsubmit",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400
    assert "já avaliada" in response.json()["detail"].lower()
    assert "correção" in response.json()["detail"].lower()


# --- 7. POST /assignments/{assignment_id}/submissions/publish-evaluations (Liberação em Lote) ---


@pytest.mark.asyncio
async def test_publish_evaluations_when_teacher_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Avaliação preliminar salva como rascunho
    await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 8.5, "publish": False},
        headers=tenant.teacher.auth_headers,
    )

    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["assignment_id"] == str(assignment_without_submissions.id)
    assert data["published_count"] == 1
    assert "sucesso" in data["message"].lower()

    # Confirma que a submissão agora está publicada
    check_res = await async_client.get(
        f"/api/v1/submissions/{submission_awaiting_review.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert check_res.json()["status"] == "published"
    assert float(check_res.json()["grade"]) == 8.5


@pytest.mark.asyncio
async def test_publish_evaluations_when_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_publish_evaluations_when_admin_or_owner_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Apenas o professor da turma pode liberar correções
    res_admin = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 403

    res_owner = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 403


@pytest.mark.asyncio
async def test_publish_evaluations_when_other_org_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    assignment_without_submissions: Assignment,
):
    other_tenant = await create_tenant("Outra Instituição Batch")
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_publish_evaluations_when_assignment_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.post(
        f"/api/v1/assignments/{uuid.uuid4()}/submissions/publish-evaluations",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_publish_evaluations_with_selective_submission_ids_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    # Salva rascunho de avaliação para a submissão
    await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/evaluation",
        json={"grade": 9.5, "publish": False},
        headers=tenant.teacher.auth_headers,
    )

    # Libera seletivamente passando o ID
    payload = {"submission_ids": [str(submission_awaiting_review.id)]}
    response = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/publish-evaluations",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["published_count"] == 1


@pytest.mark.asyncio
async def test_list_submissions_with_search_query_and_student_id_filters(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    student = submission_awaiting_review.student
    # Busca por query de texto
    res_q = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions?q={student.full_name[:4]}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_q.status_code == 200
    assert len(res_q.json()) == 1

    # Busca por student_id
    res_sid = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions?student_id={student.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_sid.status_code == 200
    assert len(res_sid.json()) == 1

    # Busca por termo inexistente
    res_none = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions?q=nao_existe_xyz_123",
        headers=tenant.teacher.auth_headers,
    )
    assert res_none.status_code == 200
    assert len(res_none.json()) == 0


# --- 8. GET /assignments/{assignment_id}/submissions/stats (Métricas da Tarefa) ---


@pytest.mark.asyncio
async def test_get_assignment_stats_when_teacher_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["assignment_id"] == str(assignment_without_submissions.id)
    assert data["total_submissions"] == 1
    assert data["awaiting_review"] == 1
    assert data["published"] == 0


@pytest.mark.asyncio
async def test_get_assignment_stats_when_admin_or_owner_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    res_admin = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 200

    res_owner = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 200


@pytest.mark.asyncio
async def test_get_assignment_stats_when_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_assignment_stats_when_other_org_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    assignment_without_submissions: Assignment,
):
    other_tenant = await create_tenant("Outra Instituição Stats")
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_assignment_stats_when_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.get(
        f"/api/v1/assignments/{uuid.uuid4()}/submissions/stats",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_assignment_stats_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    assignment_without_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/stats",
    )
    assert response.status_code == 401


# ============================================================================
# TESTES DE CONTRATO DA CONSULTA GLOBAL (GET /submissions)
# ============================================================================


@pytest.mark.asyncio
async def test_global_list_submissions_when_student_should_return_200_with_own_submissions(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        "/api/v1/submissions",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Valida que todas as submissões retornadas pertencem ao estudante logado
    for item in data:
        assert item["student"]["id"] == str(tenant.student.user.id)
        assert "ai_insight_status" not in item  # Segregação estrita por design
        assert "assignment" in item
        if item["assignment"]:
            assert "id" in item["assignment"]
            assert "title" in item["assignment"]
            assert "type" in item["assignment"]
            assert "classroom_id" in item["assignment"]


@pytest.mark.asyncio
async def test_global_list_submissions_when_student_filters_by_status(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # 1. Filtro por status=awaiting_review (encontra a submissão existente)
    res_awaiting = await async_client.get(
        "/api/v1/submissions?status=awaiting_review",
        headers=tenant.student.auth_headers,
    )
    assert res_awaiting.status_code == 200
    data_awaiting = res_awaiting.json()
    assert len(data_awaiting) >= 1
    assert all(item["status"] == "awaiting_review" for item in data_awaiting)

    # 2. Filtro por status=published (não há submissões publicadas para este aluno)
    res_published = await async_client.get(
        "/api/v1/submissions?status=published",
        headers=tenant.student.auth_headers,
    )
    assert res_published.status_code == 200
    data_published = res_published.json()
    assert len(data_published) == 0


@pytest.mark.asyncio
async def test_global_list_submissions_when_student_filters_by_classroom(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
    assignment_with_submissions: Assignment,
):
    # Sala válida
    res_ok = await async_client.get(
        f"/api/v1/submissions?classroom_id={assignment_with_submissions.classroom_id}",
        headers=tenant.student.auth_headers,
    )
    assert res_ok.status_code == 200
    data_ok = res_ok.json()
    assert len(data_ok) >= 1
    assert all(
        item["assignment"]["classroom_id"]
        == str(assignment_with_submissions.classroom_id)
        for item in data_ok
    )

    # Sala aleatória/inexistente
    res_empty = await async_client.get(
        f"/api/v1/submissions?classroom_id={uuid.uuid4()}",
        headers=tenant.student.auth_headers,
    )
    assert res_empty.status_code == 200
    assert len(res_empty.json()) == 0


@pytest.mark.asyncio
async def test_global_list_submissions_when_teacher_should_return_200_with_ai_insight_status(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        "/api/v1/submissions",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Docente tem acesso a ai_insight_status
    assert "ai_insight_status" in data[0]


@pytest.mark.asyncio
async def test_global_list_submissions_when_teacher_filters_by_student_and_query(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # Filtro por student_id
    res_student = await async_client.get(
        f"/api/v1/submissions?student_id={tenant.student.user.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_student.status_code == 200
    assert len(res_student.json()) >= 1

    # Filtro por busca textual q
    res_q = await async_client.get(
        f"/api/v1/submissions?q={tenant.student.user.full_name[:4]}",
        headers=tenant.teacher.auth_headers,
    )
    assert res_q.status_code == 200
    assert len(res_q.json()) >= 1


@pytest.mark.asyncio
async def test_global_list_submissions_when_admin_or_owner_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    res_admin = await async_client.get(
        "/api/v1/submissions",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 200
    assert len(res_admin.json()) >= 1

    res_owner = await async_client.get(
        "/api/v1/submissions",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 200
    assert len(res_owner.json()) >= 1


@pytest.mark.asyncio
async def test_global_list_submissions_when_other_org_member_should_isolate_tenant(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    submission_awaiting_review: Submission,
):
    other_tenant = await create_tenant("Outra Instituição Global Subs")
    response = await async_client.get(
        "/api/v1/submissions",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    # Isolamento de tenant: não visualiza nenhuma submissão da outra instituição
    assert len(response.json()) == 0


@pytest.mark.asyncio
async def test_global_list_submissions_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
):
    response = await async_client.get("/api/v1/submissions")
    assert response.status_code == 401


# ============================================================================
# TESTES DE CONTRATO DA LISTAGEM POR SALA (GET /classrooms/{id}/submissions)
# ============================================================================


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_teacher_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert "ai_insight_status" in data[0]


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_enrolled_student_should_return_200_own_submissions(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    for item in data:
        assert item["student"]["id"] == str(tenant.student.user.id)
        assert "ai_insight_status" not in item


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_student_filters_by_status(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
    submission_awaiting_review: Submission,
):
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions?status=awaiting_review",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert all(item["status"] == "awaiting_review" for item in data)


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_unenrolled_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
):
    # other_student pertence à organização, mas não está matriculado na sala da atividade
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_other_org_member_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    assignment_with_submissions: Assignment,
):
    other_tenant = await create_tenant("Outra Instituição Turma Subs")
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.get(
        f"/api/v1/classrooms/{uuid.uuid4()}/submissions",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_classroom_list_submissions_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    assignment_with_submissions: Assignment,
):
    response = await async_client.get(
        f"/api/v1/classrooms/{assignment_with_submissions.classroom_id}/submissions",
    )
    assert response.status_code == 401


# --- 13. Testes de Rascunho / Auto-Save (PUT /assignments/{assignment_id}/submissions/draft) ---


@pytest.mark.asyncio
async def test_save_draft_submission_code_when_enrolled_student_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "def partial_solution():\n    # Em desenvolvimento\n",
        }
    }
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["assignment_id"] == str(assignment_without_submissions.id)
    assert data["student_id"] == str(tenant.student.user.id)
    assert data["status"] == "draft"
    assert data["grade"] is None
    assert "partial_solution" in data["content"]["code"]
    assert "ai_insight" not in data


@pytest.mark.asyncio
async def test_save_draft_submission_empty_code_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    payload = {
        "content": {
            "language": "python3",
            "code": "",
        }
    }
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "draft"
    assert response.json()["content"]["code"] == ""


@pytest.mark.asyncio
async def test_save_draft_submission_questionnaire_partial_answers_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    mixed_questionnaire_assignment: Assignment,
):
    payload = {
        "content": {
            "answers": [
                {"question_id": 1, "selected_option_id": "b"},
            ]
        }
    }
    response = await async_client.put(
        f"/api/v1/assignments/{mixed_questionnaire_assignment.id}/submissions/draft",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "draft"
    assert len(data["content"]["answers"]) == 1


@pytest.mark.asyncio
async def test_save_draft_submission_updates_existing_draft_idempotently_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    # 1. Primeiro rascunho
    res1 = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "v1"}},
        headers=tenant.student.auth_headers,
    )
    assert res1.status_code == 200
    sub_id = res1.json()["id"]

    # 2. Atualização do rascunho
    res2 = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "v2"}},
        headers=tenant.student.auth_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["id"] == sub_id
    assert res2.json()["content"]["code"] == "v2"
    assert res2.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_save_draft_submission_when_already_submitted_pending_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
):
    # Envio formal inicial
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions",
        json={"content": {"language": "python3", "code": "def solve(): return 1"}},
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201

    # Tentativa de auto-save sem unsubmit
    draft_res = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "def solve(): return 2"}},
        headers=tenant.student.auth_headers,
    )
    assert draft_res.status_code == 400
    assert "desfaça a entrega primeiro" in draft_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_save_draft_submission_when_already_published_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    objective_questionnaire_assignment: Assignment,
):
    # Submete questionário com política imediata (vai direto para published)
    submit_res = await async_client.post(
        f"/api/v1/assignments/{objective_questionnaire_assignment.id}/submissions",
        json={"content": {"answers": [{"question_id": 1, "selected_option_id": "b"}]}},
        headers=tenant.student.auth_headers,
    )
    assert submit_res.status_code == 201
    assert submit_res.json()["status"] == "published"

    # Tentativa de salvar rascunho
    draft_res = await async_client.put(
        f"/api/v1/assignments/{objective_questionnaire_assignment.id}/submissions/draft",
        json={"content": {"answers": []}},
        headers=tenant.student.auth_headers,
    )
    assert draft_res.status_code == 400
    assert "já foi corrigida e avaliada" in draft_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_save_draft_submission_when_deadline_expired_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_without_submissions: Assignment,
    db_session: AsyncSession,
):
    assignment_without_submissions.deadline = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.commit()

    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400
    assert "prazo" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_save_draft_submission_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    assignment_without_submissions: Assignment,
):
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_save_draft_submission_when_not_enrolled_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_save_draft_submission_when_other_org_member_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    assignment_without_submissions: Assignment,
):
    other_tenant = await create_tenant("Outra Instituição Rascunho")
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=other_tenant.student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_save_draft_submission_when_assignment_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.put(
        f"/api/v1/assignments/{uuid.uuid4()}/submissions/draft",
        json={"content": {"language": "python3", "code": "pass"}},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_save_draft_submission_when_malformed_body_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    response = await async_client.put(
        f"/api/v1/assignments/{assignment_without_submissions.id}/submissions/draft",
        json={},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 422


# --- 14. Testes de Reprocessamento de IA (POST /submissions/{submission_id}/retry-ai) ---


@pytest.mark.asyncio
async def test_retry_ai_when_teacher_of_classroom_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(submission_awaiting_review.id)
    assert data["status"] == "pending"
    assert data["ai_insight"]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_retry_ai_when_admin_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.admin.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_retry_ai_when_owner_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.owner.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_retry_ai_when_submission_already_published_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
    db_session: AsyncSession,
):
    submission_awaiting_review.status = SubmissionStatus.PUBLISHED
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400
    assert (
        "não é possível reprocessar ia para submissões já avaliadas"
        in response.json()["detail"].lower()
    )


@pytest.mark.asyncio
async def test_retry_ai_when_submission_in_draft_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
    db_session: AsyncSession,
):
    submission_awaiting_review.status = SubmissionStatus.DRAFT
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400
    assert "estado de rascunho" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retry_ai_when_objective_questionnaire_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    objective_questionnaire_on_review: Assignment,
    db_session: AsyncSession,
):
    # Cria submissão para questionário 100% objetivo
    sub = Submission(
        assignment_id=objective_questionnaire_on_review.id,
        student_id=tenant.student.user.id,
        content={"answers": [{"question_id": 1, "selected_option_id": "a"}]},
        status=SubmissionStatus.AWAITING_REVIEW,
    )
    db_session.add(sub)
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/submissions/{sub.id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400
    assert "não requer análise de ia" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retry_ai_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    submission_awaiting_review: Submission,
):
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_retry_ai_when_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
):
    # Aluno tenta disparar retry de IA -> 403 Forbidden
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retry_ai_when_other_org_teacher_should_return_403(
    async_client: AsyncClient,
    create_tenant: Callable[..., Awaitable[TenantContext]],
    submission_awaiting_review: Submission,
):
    other_tenant = await create_tenant("Outra Instituição Retry IA")
    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=other_tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_retry_ai_when_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    response = await async_client.post(
        f"/api/v1/submissions/{uuid.uuid4()}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_retry_ai_when_already_pending_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    submission_awaiting_review: Submission,
    db_session: AsyncSession,
):
    submission_awaiting_review.status = SubmissionStatus.PENDING
    await db_session.commit()

    response = await async_client.post(
        f"/api/v1/submissions/{submission_awaiting_review.id}/retry-ai",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400
    assert "já se encontra em processamento de ia" in response.json()["detail"].lower()
