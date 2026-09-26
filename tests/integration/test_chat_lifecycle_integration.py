import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ClassroomMessage
from app.models.classroom import Classroom
from tests.fixtures.tenants import TenantContext


@pytest.mark.asyncio
async def test_chat_lifecycle_integration(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    db_session: AsyncSession,
) -> None:
    """Ciclo de vida completo do chat: envio, listagem, edição, moderação e integridade relacional."""

    # 1. Matricula o segundo aluno do tenant na turma
    student_2 = tenant.other_student
    enroll_resp = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/students",
        json={"student_id": str(student_2.user.id)},
        headers=tenant.teacher.auth_headers,
    )
    assert enroll_resp.status_code == 201

    # 2. Aluno 1 posta uma dúvida no chat
    post_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Professor, teremos revisão para a prova?"},
        headers=tenant.student.auth_headers,
    )
    assert post_res.status_code == 201
    msg1_data = post_res.json()
    msg1_id = uuid.UUID(msg1_data["id"])

    # Verifica persistência direta no PostgreSQL
    msg1_db = await db_session.get(ClassroomMessage, msg1_id)
    assert msg1_db is not None
    assert msg1_db.content == "Professor, teremos revisão para a prova?"
    assert msg1_db.is_edited is False
    assert msg1_db.is_deleted is False

    # 3. Professor responde no chat
    post_teacher_res = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Sim, faremos uma sessão de dúvidas na quinta-feira."},
        headers=tenant.teacher.auth_headers,
    )
    assert post_teacher_res.status_code == 201
    msg2_id = uuid.UUID(post_teacher_res.json()["id"])

    # 4. Aluno 2 consulta o histórico e vê ambas as mensagens em ordem cronológica
    history_res = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        headers=student_2.auth_headers,
    )
    assert history_res.status_code == 200
    msgs = history_res.json()
    assert len(msgs) == 2
    assert msgs[0]["id"] == str(msg1_id)
    assert msgs[1]["id"] == str(msg2_id)

    # 5. Aluno 1 edita a própria mensagem (dentro dos 15 minutos)
    edit_res = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg1_id}",
        json={"content": "Professor, teremos revisão para a prova de sexta-feira?"},
        headers=tenant.student.auth_headers,
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["is_edited"] is True

    # Valida no PostgreSQL
    await db_session.refresh(msg1_db)
    assert msg1_db.content == "Professor, teremos revisão para a prova de sexta-feira?"
    assert msg1_db.is_edited is True

    # 6. Simula passagem do tempo (retrocede created_at em 20 minutos)
    msg1_db.created_at = datetime.now(UTC) - timedelta(minutes=20)
    await db_session.commit()

    # Tentativa do aluno 1 de editar novamente é rejeitada (janela de 15 min expirada)
    late_edit_res = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg1_id}",
        json={"content": "Outra edição tardia"},
        headers=tenant.student.auth_headers,
    )
    assert late_edit_res.status_code == 400
    assert "15 minutos" in late_edit_res.json()["detail"]

    # 7. Professor modera e exclui a mensagem (permitido mesmo após 15 min)
    del_res = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg1_id}",
        headers=tenant.teacher.auth_headers,
    )
    assert del_res.status_code == 200

    # Valida soft delete no PostgreSQL
    await db_session.refresh(msg1_db)
    assert msg1_db.is_deleted is True

    # 8. Aluno 2 verifica que mensagem deletada é retornada como tombstone com conteúdo mascarado
    history_after_del = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        headers=student_2.auth_headers,
    )
    assert history_after_del.status_code == 200
    items_after_del = history_after_del.json()
    item_ids = [m["id"] for m in items_after_del]
    assert str(msg1_id) in item_ids
    assert str(msg2_id) in item_ids

    # Validação do tombstone para o cliente
    deleted_item = next(m for m in items_after_del if m["id"] == str(msg1_id))
    assert deleted_item["is_deleted"] is True
    assert deleted_item["content"] == "[Esta mensagem foi apagada]"

    # Confirmação no PostgreSQL de que a mensagem permanece persistida para auditoria com o conteúdo original
    msg1_audit = await db_session.get(ClassroomMessage, msg1_id)
    assert msg1_audit is not None
    assert msg1_audit.is_deleted is True
    assert (
        msg1_audit.content
        == "Professor, teremos revisão para a prova de sexta-feira?"
    )

    # 9. Cascata relacional: exclusão da sala de aula remove todas as mensagens associadas
    del_class_res = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert del_class_res.status_code == 204

    # Confirmação no PostgreSQL de que mensagens foram removidas em cascata
    stmt = select(ClassroomMessage).where(
        ClassroomMessage.classroom_id == classroom_with_student.id
    )
    result = await db_session.execute(stmt)
    assert len(result.scalars().all()) == 0
