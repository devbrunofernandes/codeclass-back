import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
)
from app.models.classroom import Classroom
from app.services.chat_service import chat_service
from app.services.websocket_manager import ConnectionManager
from tests.fixtures.tenants import TenantContext

# --- Testes Unitários de WebSocket ConnectionManager ---


@pytest.mark.asyncio
async def test_connection_manager_connect_and_disconnect() -> None:
    manager = ConnectionManager()
    room_id = uuid.uuid4()
    mock_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, mock_ws)
    assert room_id in manager._rooms
    assert mock_ws in manager._rooms[room_id]

    manager.disconnect(room_id, mock_ws)
    assert room_id not in manager._rooms


@pytest.mark.asyncio
async def test_connection_manager_broadcast_success() -> None:
    manager = ConnectionManager()
    room_id = uuid.uuid4()
    ws1 = AsyncMock(spec=WebSocket)
    ws2 = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, ws1)
    await manager.connect(room_id, ws2)

    payload = {"type": "test", "data": "hello"}
    await manager.broadcast(room_id, payload)

    ws1.send_json.assert_awaited_once_with(payload)
    ws2.send_json.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_connection_manager_broadcast_dead_socket_cleanup() -> None:
    manager = ConnectionManager()
    room_id = uuid.uuid4()
    dead_ws = AsyncMock(spec=WebSocket)
    dead_ws.send_json.side_effect = RuntimeError("Broken pipe")
    live_ws = AsyncMock(spec=WebSocket)

    await manager.connect(room_id, dead_ws)
    await manager.connect(room_id, live_ws)

    await manager.broadcast(room_id, {"type": "ping"})

    live_ws.send_json.assert_awaited_once()
    assert dead_ws not in manager._rooms[room_id]
    assert live_ws in manager._rooms[room_id]


# --- Testes Unitários de ChatService e Regras de Negócio ---


@pytest.mark.asyncio
async def test_chat_service_send_and_list_messages(
    tenant: TenantContext,
    classroom: Classroom,
    db_session: AsyncSession,
) -> None:
    # Arrange & Act: Aluno 1 envia 2 mensagens
    msg1 = await chat_service.send_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Primeira mensagem",
        db=db_session,
    )
    msg2 = await chat_service.send_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Segunda mensagem",
        db=db_session,
    )

    # Assert envio
    assert msg1.content == "Primeira mensagem"
    assert msg2.content == "Segunda mensagem"
    assert not msg1.is_edited
    assert not msg1.is_deleted

    # Act listagem
    history = await chat_service.list_messages(
        classroom_id=classroom.id,
        limit=50,
        before=None,
        db=db_session,
    )

    # Assert listagem em ordem cronológica (antigas primeiro)
    assert len(history) == 2
    assert history[0].id == msg1.id
    assert history[1].id == msg2.id


@pytest.mark.asyncio
async def test_chat_service_list_messages_includes_deleted_and_masks_content(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: 1 mensagem ativa e 1 deletada
    active = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem ativa",
        is_deleted=False,
    )
    deleted = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Conteúdo confidencial deletado",
        is_deleted=True,
    )

    # Act
    history = await chat_service.list_messages(
        classroom_id=classroom.id,
        limit=50,
        before=None,
        db=db_session,
    )

    # Assert: ambas as mensagens são retornadas (tombstone)
    msg_ids = [m.id for m in history]
    assert active.id in msg_ids
    assert deleted.id in msg_ids

    # Valida mascaramento no to_response
    active_resp = chat_service.to_response(
        next(m for m in history if m.id == active.id)
    )
    deleted_resp = chat_service.to_response(
        next(m for m in history if m.id == deleted.id)
    )

    assert active_resp.content == "Mensagem ativa"
    assert active_resp.is_deleted is False

    assert deleted_resp.content == "[Esta mensagem foi apagada]"
    assert deleted_resp.is_deleted is True
    assert "confidencial" not in deleted_resp.content


@pytest.mark.asyncio
async def test_chat_service_edit_message_within_15_mins(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem criada há 5 minutos
    created_at = datetime.now(UTC) - timedelta(minutes=5)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Texto original",
        created_at=created_at,
    )

    # Act
    edited = await chat_service.edit_message(
        classroom_id=classroom.id,
        message_id=msg.id,
        user_id=tenant.student.user.id,
        content="Texto corrigido",
        db=db_session,
    )

    # Assert
    assert edited.content == "Texto corrigido"
    assert edited.is_edited is True


@pytest.mark.asyncio
async def test_chat_service_edit_message_after_15_mins_raises_400(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem criada há 16 minutos
    created_at = datetime.now(UTC) - timedelta(minutes=16)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Texto original",
        created_at=created_at,
    )

    # Act & Assert
    with pytest.raises(BadRequestException) as exc:
        await chat_service.edit_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            user_id=tenant.student.user.id,
            content="Tentativa de edição tardia",
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "15 minutos" in exc.value.message


@pytest.mark.asyncio
async def test_chat_service_edit_message_by_non_author_raises_403(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem do aluno
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Texto original",
    )

    # Act & Assert: Professor tenta editar mensagem do aluno -> Proibido
    with pytest.raises(ForbiddenException) as exc:
        await chat_service.edit_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            user_id=tenant.teacher.user.id,
            content="Tentativa de edição por terceiro",
            db=db_session,
        )
    assert exc.value.status_code == 403
    assert "autor" in exc.value.message


@pytest.mark.asyncio
async def test_chat_service_edit_deleted_message_raises_400(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem já apagada
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Texto apagado",
        is_deleted=True,
    )

    # Act & Assert
    with pytest.raises(BadRequestException) as exc:
        await chat_service.edit_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            user_id=tenant.student.user.id,
            content="Tentativa de reviver",
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "excluída" in exc.value.message


@pytest.mark.asyncio
async def test_chat_service_delete_message_author_within_15_mins(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem de 10 min atrás
    created_at = datetime.now(UTC) - timedelta(minutes=10)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem própria",
        created_at=created_at,
    )

    # Act: Aluno exclui própria mensagem
    deleted = await chat_service.delete_message(
        classroom_id=classroom.id,
        message_id=msg.id,
        member=tenant.student.member,
        is_teacher_of_class=False,
        db=db_session,
    )

    # Assert
    assert deleted.is_deleted is True


@pytest.mark.asyncio
async def test_chat_service_delete_message_author_after_15_mins_raises_400(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem de 20 min atrás
    created_at = datetime.now(UTC) - timedelta(minutes=20)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem antiga",
        created_at=created_at,
    )

    # Act & Assert: Aluno tenta excluir após 15 minutos -> 400
    with pytest.raises(BadRequestException) as exc:
        await chat_service.delete_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            member=tenant.student.member,
            is_teacher_of_class=False,
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "15 minutos" in exc.value.message


@pytest.mark.asyncio
async def test_chat_service_delete_message_teacher_moderation_unrestricted(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem criada por aluno há 2 dias
    created_at = datetime.now(UTC) - timedelta(days=2)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem antiga de aluno",
        created_at=created_at,
    )

    # Act: Professor da turma modera e exclui sem restrição de tempo
    deleted = await chat_service.delete_message(
        classroom_id=classroom.id,
        message_id=msg.id,
        member=tenant.teacher.member,
        is_teacher_of_class=True,
        db=db_session,
    )

    # Assert
    assert deleted.is_deleted is True


@pytest.mark.asyncio
async def test_chat_service_delete_message_admin_moderation_unrestricted(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem criada há 1 dia
    created_at = datetime.now(UTC) - timedelta(days=1)
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem para moderação",
        created_at=created_at,
    )

    # Act: Admin da organização exclui mensagem
    deleted = await chat_service.delete_message(
        classroom_id=classroom.id,
        message_id=msg.id,
        member=tenant.admin.member,
        is_teacher_of_class=False,
        db=db_session,
    )

    # Assert
    assert deleted.is_deleted is True


@pytest.mark.asyncio
async def test_chat_service_delete_message_by_other_student_raises_403(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange: Mensagem do Aluno 1
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Mensagem do aluno 1",
    )

    # Act & Assert: Outro aluno tenta excluir -> 403
    with pytest.raises(ForbiddenException) as exc:
        await chat_service.delete_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            member=tenant.other_student.member,
            is_teacher_of_class=False,
            db=db_session,
        )
    assert exc.value.status_code == 403
    assert "moderadores" in exc.value.message


@pytest.mark.asyncio
async def test_chat_service_delete_already_deleted_raises_400(
    tenant: TenantContext,
    classroom: Classroom,
    create_classroom_message,
    db_session: AsyncSession,
) -> None:
    # Arrange
    msg = await create_classroom_message(
        classroom_id=classroom.id,
        sender_id=tenant.student.user.id,
        content="Já apagada",
        is_deleted=True,
    )

    # Act & Assert
    with pytest.raises(BadRequestException) as exc:
        await chat_service.delete_message(
            classroom_id=classroom.id,
            message_id=msg.id,
            member=tenant.teacher.member,
            is_teacher_of_class=True,
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "já foi excluída" in exc.value.message
