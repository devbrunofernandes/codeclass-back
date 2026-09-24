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
