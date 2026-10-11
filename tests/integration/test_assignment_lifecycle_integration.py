import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SubmissionStatus
from app.models.submission import Submission
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_full_assignment_lifecycle_and_security(
    async_client: AsyncClient, tenant: TenantContext, db_session: AsyncSession
):
    # 1. Arrange: Professor cria uma sala de aula
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Estruturas Avançadas"},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    # Matricula o aluno
    enroll_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert enroll_res.status_code == 201

    # 2. Professor cria atividade de código
    code_payload = {
        "title": "Árvore Rubro-Negra",
        "description": "Implementação completa de rotações",
        "type": "code",
        "release_policy": "on_review",
        "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        "config": {
            "languages": [{"name": "python3", "starter_code": "class RBTree: pass"}],
            "time_limit_sec": 2.5,
            "memory_limit_mb": 256,
            "rubric": "Rubrica secreta do professor para IA",
            "test_cases": [
                {"id": 1, "input": "insert 10\n", "expected_output": "ok\n"}
            ],
        },
    }
    create_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json=code_payload,
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert create_res.status_code == 201
    code_assignment_id = create_res.json()["id"]
    assert "rubric" in create_res.json()["config"]

    # 3. Aluno consulta a atividade criada: verifica conformidade com HLD 9.4 (zero vazamento de rubrica)
    student_get_res = await async_client.get(
        f"/api/v1/assignments/{code_assignment_id}",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert student_get_res.status_code == 200
    student_data = student_get_res.json()
    assert "rubric" not in student_data["config"]
    assert len(student_data["config"]["test_cases"]) == 1

    # 4. Aluno lista atividades da turma
    list_res = await async_client.get(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert "rubric" not in list_res.json()[0]["config"]

    # 5. Professor atualiza prazo e título da tarefa
    patch_res = await async_client.patch(
        f"/api/v1/assignments/{code_assignment_id}",
        json={"title": "Árvore Rubro-Negra (Prazo Prorrogado)"},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Árvore Rubro-Negra (Prazo Prorrogado)"

    # 6. Simulação de integridade relacional: vincula uma submissão diretamente no banco
    submission = Submission(
        id=uuid.uuid4(),
        assignment_id=uuid.UUID(code_assignment_id),
        student_id=tenant.student.user.id,
        content={"code": "class RBTree: pass"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(submission)
    await db_session.commit()

    # Tentativa de exclusão bloqueada devido a submissão ativa existente
    blocked_delete_res = await async_client.delete(
        f"/api/v1/assignments/{code_assignment_id}",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert blocked_delete_res.status_code == 400

    # 7. Remoção da submissão do banco e exclusão com sucesso
    await db_session.delete(submission)
    await db_session.commit()

    delete_res = await async_client.delete(
        f"/api/v1/assignments/{code_assignment_id}",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert delete_res.status_code == 204

    # Confirmação de que a atividade não existe mais
    check_deleted = await async_client.get(
        f"/api/v1/assignments/{code_assignment_id}",
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert check_deleted.status_code == 404


@pytest.mark.asyncio
async def test_student_my_assignments_lifecycle_integration(
    async_client: AsyncClient,
    tenant: TenantContext,
    db_session: AsyncSession,
):
    # 1. Arrange: Professor cria turma e matricula aluno
    class_res = await async_client.post(
        f"/api/v1/orgs/{tenant.org.id}/classrooms",
        json={"name": "Turma de Algoritmos Discente"},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert class_res.status_code == 201
    classroom_id = class_res.json()["id"]

    enroll_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/students",
        json={"student_id": str(tenant.student.user.id)},
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert enroll_res.status_code == 201

    # 2. Professor cria 1ª atividade (prazo futuro)
    code_payload = {
        "title": "Lista 1 - Grafos",
        "description": "Busca em Largura",
        "type": "code",
        "release_policy": "on_review",
        "deadline": (datetime.now(UTC) + timedelta(days=5)).isoformat(),
        "config": {
            "languages": [{"name": "python3", "starter_code": "def bfs(): pass"}],
            "time_limit_sec": 2.0,
            "memory_limit_mb": 128,
            "rubric": "Rubrica do professor",
            "test_cases": [{"id": 1, "input": "1\n", "expected_output": "1\n"}],
        },
    }
    create_res1 = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json=code_payload,
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert create_res1.status_code == 201
    assignment1_id = create_res1.json()["id"]

    # 3. Aluno verifica tarefas pendentes (estado inicial: pending, has_draft=False)
    my_res1 = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert my_res1.status_code == 200
    items1 = my_res1.json()
    assert len(items1) == 1
    assert items1[0]["id"] == assignment1_id
    assert items1[0]["student_status"] == "pending"
    assert items1[0]["has_draft"] is False
    assert items1[0]["submission"] is None

    sum_res1 = await async_client.get(
        "/api/v1/assignments/my-assignments/summary",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert sum_res1.status_code == 200
    assert sum_res1.json() == {
        "total": 1,
        "pending": 1,
        "overdue": 0,
        "submitted": 0,
        "graded": 0,
    }

    # 4. Aluno salva rascunho: status continua pending, mas has_draft=True
    draft_res = await async_client.put(
        f"/api/v1/assignments/{assignment1_id}/submissions/draft",
        json={"content": {"language": "python3", "code": "# rascunho inicial"}},
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert draft_res.status_code == 200

    my_res2 = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert my_res2.status_code == 200
    items2 = my_res2.json()
    assert len(items2) == 1
    assert items2[0]["student_status"] == "pending"
    assert items2[0]["has_draft"] is True
    assert items2[0]["submission"] is None

    # 5. Aluno realiza entrega formal: status passa a submitted, has_draft=False
    submit_res = await async_client.post(
        f"/api/v1/assignments/{assignment1_id}/submissions",
        json={"content": {"language": "python3", "code": "def bfs(): return [1]"}},
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert submit_res.status_code == 201

    my_res3 = await async_client.get(
        "/api/v1/assignments/my-assignments",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert my_res3.status_code == 200
    items3 = my_res3.json()
    assert len(items3) == 1
    assert items3[0]["student_status"] == "submitted"
    assert items3[0]["has_draft"] is False
    assert items3[0]["submission"] is not None
    assert items3[0]["submission"]["status"] in ("pending", "awaiting_review")

    # 6. Professor cria 2ª atividade (prazo no passado)
    overdue_payload = {
        "title": "Quiz Antigo",
        "description": "Prazo já expirou",
        "type": "code",
        "release_policy": "on_review",
        "deadline": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "config": {
            "languages": [{"name": "python3", "starter_code": "def old(): pass"}],
            "time_limit_sec": 1.0,
            "memory_limit_mb": 64,
            "rubric": "",
            "test_cases": [],
        },
    }
    create_res2 = await async_client.post(
        f"/api/v1/classrooms/{classroom_id}/assignments",
        json=overdue_payload,
        headers={"Authorization": f"Bearer {tenant.teacher.token}"},
    )
    assert create_res2.status_code == 201

    # 7. Aluno consulta summary consolidado: 1 submitted + 1 overdue = 2 total
    sum_res2 = await async_client.get(
        "/api/v1/assignments/my-assignments/summary",
        headers={"Authorization": f"Bearer {tenant.student.token}"},
    )
    assert sum_res2.status_code == 200
    assert sum_res2.json() == {
        "total": 2,
        "pending": 0,
        "overdue": 1,
        "submitted": 1,
        "graded": 0,
    }
