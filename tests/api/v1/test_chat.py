import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import pytest
from httpx import AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.database import engine
from app.main import app
from app.models.classroom import Classroom
from tests.fixtures.tenants import TenantContext

# --- Testes de Envio de Mensagem (POST /classrooms/{id}/messages) ---


@pytest.mark.asyncio
async def test_send_message_as_enrolled_student_should_return_201(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    # Act: Aluno matriculado envia mensagem
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Olá, professor! Quando sai a nota?"},
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 201
    data = response.json()
    assert data["classroom_id"] == str(classroom_with_student.id)
    assert data["content"] == "Olá, professor! Quando sai a nota?"
    assert data["sender"]["id"] == str(tenant.student.user.id)
    assert data["sender"]["role"] == "student"
    assert data["is_edited"] is False
    assert data["is_deleted"] is False


@pytest.mark.asyncio
async def test_send_message_as_teacher_and_admin_should_return_201(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    # Teacher envia aviso
    resp_teacher = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Aviso da aula de amanhã."},
        headers=tenant.teacher.auth_headers,
    )
    assert resp_teacher.status_code == 201
    assert resp_teacher.json()["sender"]["role"] == "teacher"

    # Admin envia aviso de supervisão
    resp_admin = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Mensagem institucional da coordenação."},
        headers=tenant.admin.auth_headers,
    )
    assert resp_admin.status_code == 201


@pytest.mark.asyncio
async def test_send_message_when_unauthenticated_should_return_401(
    async_client: AsyncClient,
    classroom_with_student: Classroom,
) -> None:
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Mensagem anônima"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_send_message_when_not_enrolled_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    # other_student não está matriculado na sala
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Tentativa de intromissão"},
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_send_message_when_other_teacher_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    # other_teacher é professor de outra turma, não desta
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Tentativa de outro professor"},
        headers=tenant.other_teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_send_message_cross_tenant_should_return_403(
    async_client: AsyncClient,
    create_tenant: Any,
    classroom_with_student: Classroom,
) -> None:
    other_tenant = await create_tenant("Outra Faculdade")
    response = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "Invasão de tenant"},
        headers=other_tenant.student.auth_headers,
    )
    assert response.status_code in (403, 404)


@pytest.mark.asyncio
async def test_send_message_invalid_payload_should_return_422(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    # Body vazio
    resp1 = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={},
        headers=tenant.student.auth_headers,
    )
    assert resp1.status_code == 422

    # Conteúdo vazio ou apenas espaços
    resp2 = await async_client.post(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        json={"content": "   "},
        headers=tenant.student.auth_headers,
    )
    assert resp2.status_code == 422


# --- Testes de Listagem de Histórico (GET /classrooms/{id}/messages) ---


@pytest.mark.asyncio
async def test_list_messages_history_with_pagination_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Cria 3 mensagens espaçadas no tempo
    base_time = datetime.now(UTC) - timedelta(minutes=10)
    msg1 = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Msg 1",
        created_at=base_time,
    )
    msg2 = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.teacher.user.id,
        content="Msg 2",
        created_at=base_time + timedelta(minutes=2),
    )
    msg3 = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Msg 3",
        created_at=base_time + timedelta(minutes=4),
    )

    # Act 1: Lista tudo
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 3
    # Ordem cronológica (antigas primeiro)
    assert items[0]["id"] == str(msg1.id)
    assert items[1]["id"] == str(msg2.id)
    assert items[2]["id"] == str(msg3.id)

    # Act 2: Paginação com limit=2
    res_limit = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages?limit=2",
        headers=tenant.student.auth_headers,
    )
    assert res_limit.status_code == 200
    assert len(res_limit.json()) == 2

    # Act 3: Paginação com before (mensagens anteriores à msg3)
    res_before = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages?before={quote(msg3.created_at.isoformat())}",
        headers=tenant.student.auth_headers,
    )
    assert res_before.status_code == 200
    before_items = res_before.json()
    assert len(before_items) == 2
    assert str(msg3.id) not in [item["id"] for item in before_items]


@pytest.mark.asyncio
async def test_list_messages_includes_deleted_messages_with_masked_content_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: 1 mensagem ativa e 1 mensagem deletada
    active = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem visível",
        is_deleted=False,
    )
    deleted = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.teacher.user.id,
        content="Mensagem sensível deletada",
        is_deleted=True,
    )

    # Act
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    items = response.json()
    item_ids = [m["id"] for m in items]
    assert str(active.id) in item_ids
    assert str(deleted.id) in item_ids

    # Valida conteúdo e flag de tombstone
    active_item = next(m for m in items if m["id"] == str(active.id))
    deleted_item = next(m for m in items if m["id"] == str(deleted.id))

    assert active_item["content"] == "Mensagem visível"
    assert active_item["is_deleted"] is False

    assert deleted_item["content"] == "[Esta mensagem foi apagada]"
    assert deleted_item["is_deleted"] is True
    assert "sensível" not in deleted_item["content"]


@pytest.mark.asyncio
async def test_list_messages_when_not_enrolled_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    response = await async_client.get(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


# --- Testes de Edição de Mensagem (PATCH /classrooms/{id}/messages/{msg_id}) ---


@pytest.mark.asyncio
async def test_edit_message_within_15_mins_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem enviada há 5 minutos pelo aluno
    created_at = datetime.now(UTC) - timedelta(minutes=5)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem antes da edição",
        created_at=created_at,
    )

    # Act
    response = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        json={"content": "Mensagem editada com sucesso"},
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Mensagem editada com sucesso"
    assert data["is_edited"] is True


@pytest.mark.asyncio
async def test_edit_message_after_15_mins_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem enviada há 16 minutos
    created_at = datetime.now(UTC) - timedelta(minutes=16)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem antiga",
        created_at=created_at,
    )

    # Act
    response = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        json={"content": "Tentativa de editar após prazo"},
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 400
    assert "15 minutos" in response.json()["detail"]


@pytest.mark.asyncio
async def test_edit_message_by_other_user_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem do aluno
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem do aluno",
    )

    # Act: Professor tenta editar mensagem de aluno -> Proibido
    response = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        json={"content": "Professor tentando editar texto do aluno"},
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_edit_deleted_message_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem já apagada",
        is_deleted=True,
    )

    response = await async_client.patch(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        json={"content": "Tentando editar apagada"},
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400


# --- Testes de Exclusão e Moderação (DELETE /classrooms/{id}/messages/{msg_id}) ---


@pytest.mark.asyncio
async def test_delete_message_by_author_within_15_mins_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange
    created_at = datetime.now(UTC) - timedelta(minutes=5)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem a ser apagada pelo autor",
        created_at=created_at,
    )

    # Act
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        headers=tenant.student.auth_headers,
    )

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "message_deleted"
    assert data["message_id"] == str(msg.id)
    assert data["classroom_id"] == str(classroom_with_student.id)


@pytest.mark.asyncio
async def test_delete_message_by_author_after_15_mins_should_return_400(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: 20 minutos atrás
    created_at = datetime.now(UTC) - timedelta(minutes=20)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem antiga",
        created_at=created_at,
    )

    # Act
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        headers=tenant.student.auth_headers,
    )
    assert response.status_code == 400
    assert "15 minutos" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_message_by_teacher_after_15_mins_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem criada há 2 dias por aluno
    created_at = datetime.now(UTC) - timedelta(days=2)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem inadequada de 2 dias atrás",
        created_at=created_at,
    )

    # Act: Professor modera a qualquer momento
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["type"] == "message_deleted"


@pytest.mark.asyncio
async def test_delete_message_by_admin_should_return_200(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem antiga
    created_at = datetime.now(UTC) - timedelta(hours=5)
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem que o admin removerá",
        created_at=created_at,
    )

    # Act: Admin modera
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        headers=tenant.admin.auth_headers,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_delete_message_by_other_student_should_return_403(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
    create_classroom_message: Any,
) -> None:
    # Arrange: Mensagem do Aluno 1
    msg = await create_classroom_message(
        classroom_id=classroom_with_student.id,
        sender_id=tenant.student.user.id,
        content="Mensagem do aluno 1",
    )

    # Aluno 2 tenta excluir
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg.id}",
        headers=tenant.other_student.auth_headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_message_not_found_should_return_404(
    async_client: AsyncClient,
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    response = await async_client.delete(
        f"/api/v1/classrooms/{classroom_with_student.id}/messages/{uuid.uuid4()}",
        headers=tenant.teacher.auth_headers,
    )
    assert response.status_code == 404


# --- Testes de Conexão WebSocket e Streaming em Tempo Real ---


@pytest.mark.asyncio
async def test_websocket_chat_without_token_should_reject(
    classroom_with_student: Classroom,
) -> None:
    await engine.dispose()
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/v1/classrooms/{classroom_with_student.id}/chat/ws"
        ),
    ):
        pass
    await engine.dispose()


@pytest.mark.asyncio
async def test_websocket_chat_with_unauthorized_user_should_reject(
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    await engine.dispose()
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/v1/classrooms/{classroom_with_student.id}/chat/ws?token={tenant.other_student.token}"
        ),
    ):
        pass
    await engine.dispose()


@pytest.mark.asyncio
async def test_websocket_chat_connected_and_broadcast_flow(
    tenant: TenantContext,
    classroom_with_student: Classroom,
) -> None:
    await engine.dispose()
    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/api/v1/classrooms/{classroom_with_student.id}/chat/ws?token={tenant.student.token}"
        ) as ws,
    ):
        # Envia mensagem via REST usando o client
        post_resp = client.post(
            f"/api/v1/classrooms/{classroom_with_student.id}/messages",
            json={"content": "Mensagem via REST para testar WebSocket"},
            headers=tenant.student.auth_headers,
        )
        assert post_resp.status_code == 201
        msg_id = post_resp.json()["id"]

        # O WebSocket deve receber o evento de nova mensagem
        event_new = ws.receive_json()
        assert event_new["type"] == "new_message"
        assert event_new["data"]["content"] == "Mensagem via REST para testar WebSocket"

        # Edita a mensagem via REST
        patch_resp = client.patch(
            f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg_id}",
            json={"content": "Mensagem corrigida via REST"},
            headers=tenant.student.auth_headers,
        )
        assert patch_resp.status_code == 200

        # O WebSocket deve receber o evento de mensagem editada
        event_edit = ws.receive_json()
        assert event_edit["type"] == "message_edited"
        assert event_edit["data"]["content"] == "Mensagem corrigida via REST"
        assert event_edit["data"]["is_edited"] is True

        # Exclui a mensagem via REST
        del_resp = client.delete(
            f"/api/v1/classrooms/{classroom_with_student.id}/messages/{msg_id}",
            headers=tenant.student.auth_headers,
        )
        assert del_resp.status_code == 200

        # O WebSocket deve receber o evento de mensagem excluída
        event_del = ws.receive_json()
        assert event_del["type"] == "message_deleted"
        assert event_del["message_id"] == msg_id

        # Testa ping / pong no WebSocket
        ws.send_text('{"type": "ping"}')
        pong = ws.receive_json()
        assert pong == {"type": "pong"}

        # Envia texto inválido (ignorado sem quebrar)
        ws.send_text("not a json")
    await engine.dispose()


@pytest.mark.asyncio
async def test_websocket_chat_with_invalid_token_should_reject(
    classroom_with_student: Classroom,
) -> None:
    await engine.dispose()
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/v1/classrooms/{classroom_with_student.id}/chat/ws?token=invalid.jwt.token"
        ),
    ):
        pass
    await engine.dispose()


@pytest.mark.asyncio
async def test_websocket_chat_cross_tenant_should_reject(
    classroom_with_student: Classroom,
    create_tenant: Any,
) -> None:
    other_tenant = await create_tenant("Outra Facul")
    await engine.dispose()
    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            f"/api/v1/classrooms/{classroom_with_student.id}/chat/ws?token={other_tenant.student.token}"
        ),
    ):
        pass
    await engine.dispose()
