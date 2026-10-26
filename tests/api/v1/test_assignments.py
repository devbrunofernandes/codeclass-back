import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from tests.conftest import TenantContext

# --- Testes de Criação (POST /classrooms/{id}/assignments) ---


@pytest.mark.parametrize("statement", ["", "Enunciado válido"])
@pytest.mark.asyncio
async def test_update_assignment_when_config_mixes_types_should_return_422(
    async_client, tenant, assignment_without_submissions, statement
):
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json={
            "config": {
                "statement": statement,
                "languages": [{"name": "python3"}],
                "questions": [
                    {"id": 1, "type": "open", "points": 1, "statement": "Explique."}
                ],
            }
        },
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_code_assignment_when_config_is_questionnaire_should_return_400(
    async_client, tenant, assignment_without_submissions
):
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json={
            "config": {
                "questions": [
                    {"id": 1, "type": "open", "points": 1, "statement": "Explique."}
                ]
            }
        },
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.parametrize("statement", [None, "", "   ", 123, []])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
@pytest.mark.asyncio
async def test_write_assignment_when_statement_is_invalid_should_return_422(
    async_client, tenant, classroom, assignment_without_submissions, statement, method
):
    payload = {
        "title": "Soma",
        "type": "code",
        "config": {"statement": statement, "languages": [{"name": "python3"}]},
    }
    url = (
        f"/api/v1/classrooms/{classroom.id}/assignments"
        if method == "POST"
        else f"/api/v1/assignments/{assignment_without_submissions.id}"
    )
    response = await async_client.request(
        method, url, json=payload, headers=tenant.teacher.auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_assignment_when_statement_is_missing_should_return_422(
    async_client, tenant, classroom
):
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json={
            "title": "Soma",
            "type": "code",
            "config": {"languages": [{"name": "python3"}]},
        },
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_code_assignment_when_called_by_teacher_should_create_successfully_201(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange
    payload = {
        "title": "Atividade de Ordenação",
        "description": "Implemente MergeSort",
        "type": "code",
        "release_policy": "on_review",
        "config": {
            "statement": "Ordene os valores recebidos.\nUse MergeSort.",
            "languages": [{"name": "python3", "starter_code": "def mergesort(): pass"}],
            "time_limit_sec": 3.0,
            "memory_limit_mb": 256,
            "rubric": "Garantir complexidade O(n log n).",
            "test_cases": [{"id": 1, "input": "3 1 2\n", "expected_output": "1 2 3\n"}],
        },
    }

    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Atividade de Ordenação"
    assert data["type"] == "code"
    assert data["classroom_id"] == str(classroom.id)
    assert "rubric" in data["config"]
    assert data["config"]["statement"] == payload["config"]["statement"]


@pytest.mark.asyncio
async def test_create_questionnaire_assignment_when_called_by_teacher_should_create_successfully_201(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange
    payload = {
        "title": "Questionário sobre Árvores",
        "description": "Conceitos de Árvores Binárias",
        "type": "questionnaire",
        "release_policy": "on_review",
        "config": {
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "Árvore AVL é balanceada?",
                    "options": [{"id": "a", "text": "Sim"}, {"id": "b", "text": "Não"}],
                    "correct_option_id": "a",
                },
                {
                    "id": 2,
                    "type": "open",
                    "points": 5.0,
                    "statement": "Defina fator de balanceamento.",
                    "reference_answer": "Diferença entre altura esquerda e direita.",
                    "rubric": "Validar menção à altura das subárvores.",
                },
            ]
        },
    }

    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Questionário sobre Árvores"
    assert len(data["config"]["questions"]) == 2
    assert "correct_option_id" in data["config"]["questions"][0]


@pytest.mark.asyncio
async def test_create_questionnaire_100_percent_objective_with_immediate_policy_should_succeed_201(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange: RF15 - Questionário exclusivamente com perguntas de múltipla escolha permite immediate
    payload = {
        "title": "Quiz Rápido de Sintaxe",
        "description": "Perguntas objetivas com liberação imediata",
        "type": "questionnaire",
        "release_policy": "immediate",
        "config": {
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 10.0,
                    "statement": "Qual a extensão padrão de arquivos Python?",
                    "options": [{"id": "a", "text": ".py"}, {"id": "b", "text": ".js"}],
                    "correct_option_id": "a",
                }
            ]
        },
    }

    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 201
    assert response.json()["release_policy"] == "immediate"


@pytest.mark.asyncio
async def test_create_code_assignment_with_immediate_policy_should_return_422(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange: RF15 - Tarefa de código exige on_review
    payload = {
        "title": "Código Proibido Imediato",
        "type": "code",
        "release_policy": "immediate",
        "config": {
            "statement": "Implemente a solução conforme os casos de teste.",
            "languages": [{"name": "python3", "starter_code": ""}],
            "test_cases": [],
        },
    }

    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 422
    assert "não é permitida para atividades de código" in response.text


@pytest.mark.asyncio
async def test_create_questionnaire_with_open_questions_and_immediate_policy_should_return_422(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange: RF15 - Questionário com perguntas abertas não pode ter liberação imediata
    payload = {
        "title": "Questionário com Dissertativa Proibido Imediato",
        "type": "questionnaire",
        "release_policy": "immediate",
        "config": {
            "questions": [
                {
                    "id": 1,
                    "type": "open",
                    "points": 10.0,
                    "statement": "Explique a recursão.",
                    "reference_answer": "Função que chama a si mesma.",
                }
            ]
        },
    }

    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 422
    assert "restrita a questionários 100% objetivos" in response.text


@pytest.mark.asyncio
async def test_create_assignment_when_called_by_student_or_admin_should_return_403(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Arrange
    payload = {
        "title": "Atividade Proibida",
        "type": "code",
        "config": {
            "statement": "Implemente a solução conforme os casos de teste.",
            "languages": [{"name": "python3", "starter_code": ""}],
            "test_cases": [],
        },
    }

    # Act & Assert - Aluno
    res_student = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.student.auth_headers,
    )
    assert res_student.status_code == 403

    # Act & Assert - Admin (HLD RBAC: apenas Teacher da sala cria atividades)
    res_admin = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json=payload,
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 403


@pytest.mark.asyncio
async def test_create_assignment_when_payload_is_invalid_should_return_422(
    async_client: AsyncClient, tenant: TenantContext, classroom: Classroom
):
    # Act: Payload sem campos obrigatórios
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json={"title": "Incompleto"},
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_assignment_when_unauthenticated_should_return_401(
    async_client: AsyncClient, classroom: Classroom
):
    # Act
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        json={"title": "Sem Auth"},
    )
    assert response.status_code == 401


# --- Testes de Listagem (GET /classrooms/{id}/assignments) ---


@pytest.mark.asyncio
async def test_list_assignments_when_called_by_teacher_should_return_full_details_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    assignment_without_submissions: Assignment,
):
    # Act
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Professor visualiza config completo com rubrica
    assert "rubric" in data[0]["config"]


@pytest.mark.asyncio
async def test_list_assignments_when_called_by_enrolled_student_should_return_sanitized_details_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    # Act
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Estudante NÃO pode receber correct_option_id (HLD 9.4)
    questions = data[0]["config"]["questions"]
    assert "correct_option_id" not in questions[0]


@pytest.mark.asyncio
async def test_list_assignments_when_non_member_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom: Classroom,
    assignment_without_submissions: Assignment,
):
    # Act: other_student não está matriculado na turma
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom.id}/assignments",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


# --- Testes de Detalhes por ID (GET /assignments/{id}) ---


@pytest.mark.asyncio
async def test_get_assignment_by_id_when_called_by_teacher_should_return_full_config_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(assignment_without_submissions.id)
    assert "rubric" in data["config"]


@pytest.mark.asyncio
async def test_get_assignment_by_id_when_called_by_enrolled_student_should_return_sanitized_config_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    enrolled_student: ClassroomStudent,
    assignment_with_submissions: Assignment,
):
    # Act
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_with_submissions.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(assignment_with_submissions.id)
    # HLD 9.4: Gabarito suprimido
    assert "correct_option_id" not in data["config"]["questions"][0]


@pytest.mark.asyncio
async def test_get_assignment_by_id_when_non_member_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act: other_student não pertence à sala da atividade
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_assignment_by_id_when_cross_tenant_should_return_403_or_404(
    async_client: AsyncClient,
    assignment_without_submissions: Assignment,
    create_tenant,
):
    # Arrange
    other_tenant = await create_tenant("Outra Instituição")

    # Act
    response = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=other_tenant.teacher.auth_headers,
    )

    # Assert: RNF01 isolamento multi-tenant
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_get_assignment_by_id_when_not_found_should_return_404(
    async_client: AsyncClient, tenant: TenantContext
):
    # Act
    random_id = uuid.uuid4()
    response = await async_client.get(
        f"/api/v1/assignments/{random_id}",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


# --- Testes de Edição Parcial (PATCH /assignments/{id}) ---


@pytest.mark.asyncio
async def test_update_assignment_when_called_by_teacher_should_update_successfully_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    new_deadline = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    payload = {
        "title": "Busca Binária Otimizada",
        "description": "Nova descrição atualizada",
        "deadline": new_deadline,
        "config": {
            "statement": "Busque o alvo.\nRetorne -1 quando ausente.",
            "languages": [{"name": "python3", "starter_code": "# code"}],
            "time_limit_sec": 4.0,
            "memory_limit_mb": 512,
            "rubric": "Nova rubrica",
            "test_cases": [],
        },
    }

    # Act
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json=payload,
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Busca Binária Otimizada"
    assert data["description"] == "Nova descrição atualizada"
    assert data["config"]["time_limit_sec"] == 4.0
    assert data["config"]["statement"] == payload["config"]["statement"]


@pytest.mark.asyncio
async def test_update_assignment_when_clearing_deadline_should_persist_none(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Arrange & Act: Envia deadline como null
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json={"deadline": None},
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    assert response.json()["deadline"] is None


@pytest.mark.asyncio
async def test_update_assignment_when_setting_immediate_policy_on_code_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act: Tenta colocar release_policy=immediate em tarefa de código
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json={"release_policy": "immediate"},
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 400
    assert "não é permitida para atividades de código" in response.text


@pytest.mark.asyncio
async def test_update_assignment_when_called_by_non_teacher_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act: Aluno tenta atualizar
    response = await async_client.patch(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        json={"title": "Tentativa Indevida"},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 403


# --- Testes de Exclusão (DELETE /assignments/{id}) ---


@pytest.mark.asyncio
async def test_delete_assignment_when_without_submissions_should_delete_successfully_204(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act: Excluir tarefa sem submissões
    response = await async_client.delete(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 204

    # Confirma que foi excluída
    get_res = await async_client.get(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert get_res.status_code == 404


@pytest.mark.asyncio
async def test_delete_assignment_when_with_submissions_should_return_400_bad_request(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_with_submissions: Assignment,
):
    # Act: Exclusão deve ser bloqueada por integridade pedagógica
    response = await async_client.delete(
        f"/api/v1/assignments/{assignment_with_submissions.id}",
        headers=tenant.teacher.auth_headers,
    )

    # Assert
    assert response.status_code == 400
    assert "submissões" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_delete_assignment_when_called_by_student_or_admin_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    assignment_without_submissions: Assignment,
):
    # Act & Assert - Aluno
    res_student = await async_client.delete(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.student.auth_headers,
    )
    assert res_student.status_code == 403

    # Act & Assert - Admin
    res_admin = await async_client.delete(
        f"/api/v1/assignments/{assignment_without_submissions.id}",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 403


# --- Testes de Jornada do Aluno (GET /assignments/my-assignments & /summary) ---


@pytest.mark.asyncio
async def test_list_my_assignments_when_called_by_student_should_return_200_ok(
    async_client: AsyncClient,
    tenant: TenantContext,
    student_assignments_bundle,
):
    # Act
    response = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5

    by_id = {item["id"]: item for item in data}
    pending_item = by_id[str(student_assignments_bundle.pending_assignment.id)]
    assert pending_item["student_status"] == "pending"
    assert pending_item["has_draft"] is False
    assert pending_item["submission"] is None
    assert pending_item["classroom_name"] == student_assignments_bundle.classroom.name

    overdue_item = by_id[str(student_assignments_bundle.overdue_assignment.id)]
    assert overdue_item["student_status"] == "overdue"
    assert overdue_item["has_draft"] is False
    assert overdue_item["submission"] is None

    draft_item = by_id[str(student_assignments_bundle.draft_assignment.id)]
    assert draft_item["student_status"] == "pending"
    assert draft_item["has_draft"] is True
    assert draft_item["submission"] is None

    submitted_item = by_id[str(student_assignments_bundle.submitted_assignment.id)]
    assert submitted_item["student_status"] == "submitted"
    assert submitted_item["has_draft"] is False
    assert submitted_item["submission"]["status"] == "pending"

    graded_item = by_id[str(student_assignments_bundle.graded_assignment.id)]
    assert graded_item["student_status"] == "graded"
    assert graded_item["has_draft"] is False
    assert graded_item["submission"]["status"] == "published"
    assert float(graded_item["submission"]["grade"]) == 9.50


@pytest.mark.asyncio
async def test_list_my_assignments_when_filtered_by_classroom_should_return_200_ok(
    async_client: AsyncClient,
    tenant: TenantContext,
    student_assignments_bundle,
):
    # Act
    response = await async_client.get(
        f"/api/v1/assignments/my-assignments?classroom_id={student_assignments_bundle.classroom.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    assert len(response.json()) == 5


@pytest.mark.asyncio
async def test_list_my_assignments_when_filtered_by_status_should_return_200_ok(
    async_client: AsyncClient,
    tenant: TenantContext,
    student_assignments_bundle,
):
    # 1. Pending (espera 2: sem submissão e com rascunho)
    res_pending = await async_client.get(
        "/api/v1/assignments/my-assignments?status=pending",
        headers=tenant.student.auth_headers,
    )
    assert res_pending.status_code == 200
    assert len(res_pending.json()) == 2
    assert all(item["student_status"] == "pending" for item in res_pending.json())

    # 2. Overdue (espera 1)
    res_overdue = await async_client.get(
        "/api/v1/assignments/my-assignments?status=overdue",
        headers=tenant.student.auth_headers,
    )
    assert res_overdue.status_code == 200
    assert len(res_overdue.json()) == 1
    assert res_overdue.json()[0]["student_status"] == "overdue"

    # 3. Submitted (espera 1)
    res_submitted = await async_client.get(
        "/api/v1/assignments/my-assignments?status=submitted",
        headers=tenant.student.auth_headers,
    )
    assert res_submitted.status_code == 200
    assert len(res_submitted.json()) == 1
    assert res_submitted.json()[0]["student_status"] == "submitted"

    # 4. Graded (espera 1)
    res_graded = await async_client.get(
        "/api/v1/assignments/my-assignments?status=graded",
        headers=tenant.student.auth_headers,
    )
    assert res_graded.status_code == 200
    assert len(res_graded.json()) == 1
    assert res_graded.json()[0]["student_status"] == "graded"

    # 5. Unsubmitted (espera 3: pending + overdue)
    res_unsub = await async_client.get(
        "/api/v1/assignments/my-assignments?status=unsubmitted",
        headers=tenant.student.auth_headers,
    )
    assert res_unsub.status_code == 200
    assert len(res_unsub.json()) == 3
    assert all(
        item["student_status"] in ("pending", "overdue") for item in res_unsub.json()
    )


@pytest.mark.asyncio
async def test_get_my_assignments_summary_when_called_by_student_should_return_200_ok(
    async_client: AsyncClient,
    tenant: TenantContext,
    student_assignments_bundle,
):
    # Act
    response = await async_client.get(
        "/api/v1/assignments/my-assignments/summary",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["pending"] == 2
    assert data["overdue"] == 1
    assert data["submitted"] == 1
    assert data["graded"] == 1


@pytest.mark.asyncio
async def test_get_my_assignments_summary_when_filtered_by_classroom_should_return_200_ok(
    async_client: AsyncClient,
    tenant: TenantContext,
    student_assignments_bundle,
):
    # Act
    response = await async_client.get(
        f"/api/v1/assignments/my-assignments/summary?classroom_id={student_assignments_bundle.classroom.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["pending"] == 2


@pytest.mark.asyncio
async def test_list_my_assignments_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
):
    # Act
    response = await async_client.get("/api/v1/assignments/my-assignments")

    # Assert
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_my_assignments_when_called_by_teacher_or_admin_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    # Act & Assert - Professor
    res_teacher = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers=tenant.teacher.auth_headers,
    )
    assert res_teacher.status_code == 403

    # Act & Assert - Admin
    res_admin = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers=tenant.admin.auth_headers,
    )
    assert res_admin.status_code == 403

    # Act & Assert - Owner
    res_owner = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers=tenant.owner.auth_headers,
    )
    assert res_owner.status_code == 403


@pytest.mark.asyncio
async def test_list_my_assignments_when_other_org_classroom_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_tenant,
    create_classroom,
):
    # Arrange
    other_tenant = await create_tenant("Outra Faculdade API")
    other_classroom = await create_classroom(other_tenant)

    # Act
    response = await async_client.get(
        f"/api/v1/assignments/my-assignments?classroom_id={other_classroom.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 403
    assert "outra organização" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_my_assignments_when_not_enrolled_in_classroom_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    create_classroom,
):
    # Arrange: sala criada na mesma organização mas o aluno não foi matriculado
    not_enrolled_room = await create_classroom(tenant, name="Turma Isolada")

    # Act
    response = await async_client.get(
        f"/api/v1/assignments/my-assignments?classroom_id={not_enrolled_room.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 403
    assert "não é membro" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_my_assignments_when_classroom_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    # Act
    response = await async_client.get(
        f"/api/v1/assignments/my-assignments?classroom_id={uuid.uuid4()}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 404
    assert "não encontrada" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_my_assignments_when_invalid_status_filter_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
):
    # Act
    response = await async_client.get(
        "/api/v1/assignments/my-assignments?status=invalid_status",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 422
