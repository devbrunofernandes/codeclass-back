import json
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from app.api.deps import (
    ClassroomContext,
    get_db,
    require_classroom_permission,
)
from app.core.database import async_session_maker
from app.infrastructure.auth import auth_service
from app.infrastructure.realtime import connection_manager
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.schemas.message import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatMessageUpdate,
    MessageDeletedEvent,
)
from app.services.chat_service import chat_service

router = APIRouter(prefix="/classrooms")


@router.get(
    "/{classroom_id}/messages",
    response_model=list[ChatMessageResponse],
    summary="Lista histórico de mensagens da turma com suporte a paginação cronológica",
)
async def list_messages(
    classroom_id: UUID,
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[datetime | None, Query()] = None,
) -> list[ChatMessageResponse]:
    messages = await chat_service.list_messages(
        classroom_id=classroom_id,
        limit=limit,
        before=before,
        db=db,
    )
    return [chat_service.to_response(m) for m in messages]


@router.post(
    "/{classroom_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Envia mensagem de texto no chat da turma (com persistência e broadcast via WebSocket)",
)
async def send_message(
    classroom_id: UUID,
    payload: ChatMessageCreate,
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatMessageResponse:
    msg = await chat_service.send_message(
        classroom_id=classroom_id,
        sender_id=context.current_member.user_id,
        content=payload.content,
        db=db,
    )
    return chat_service.to_response(msg)


@router.patch(
    "/{classroom_id}/messages/{message_id}",
    response_model=ChatMessageResponse,
    summary="Edita o conteúdo textual de mensagem enviada (tolerância de até 15 minutos)",
)
async def edit_message(
    classroom_id: UUID,
    message_id: UUID,
    payload: ChatMessageUpdate,
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ChatMessageResponse:
    msg = await chat_service.edit_message(
        classroom_id=classroom_id,
        message_id=message_id,
        user_id=context.current_member.user_id,
        content=payload.content,
        db=db,
    )
    return chat_service.to_response(msg)


@router.delete(
    "/{classroom_id}/messages/{message_id}",
    response_model=MessageDeletedEvent,
    summary="Marca mensagem como excluída com notificação em tempo real via WebSocket",
)
async def delete_message(
    classroom_id: UUID,
    message_id: UUID,
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageDeletedEvent:
    msg = await chat_service.delete_message(
        classroom_id=classroom_id,
        message_id=message_id,
        member=context.current_member,
        is_teacher_of_class=context.is_teacher_of_class,
        db=db,
    )
    return MessageDeletedEvent(message_id=msg.id, classroom_id=classroom_id)


@router.websocket("/{classroom_id}/chat/ws")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    classroom_id: UUID,
    token: Annotated[str | None, Query()] = None,
) -> None:
    """Conexão WebSocket bidirecional para streaming e recebimento de mensagens e eventos da turma."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Handshake: autenticação e autorização via sessão efêmera
    async with async_session_maker() as session:
        try:
            payload = await auth_service.verify_jwt_token(token)
            sub = payload.get("sub")
            if not sub:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            user_id = UUID(str(sub))
        except Exception:  # noqa: BLE001
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Busca membro ativo
        member_stmt = select(OrganizationMember).where(
            OrganizationMember.user_id == user_id
        )
        member = (await session.execute(member_stmt)).scalar_one_or_none()
        if not member or not member.is_active:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Busca sala de aula
        class_stmt = select(Classroom).where(Classroom.id == classroom_id)
        classroom = (await session.execute(class_stmt)).scalar_one_or_none()
        if not classroom or classroom.organization_id != member.organization_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Checa privilégios de acesso
        is_owner = member.role == OrgRole.OWNER
        is_admin = member.role == OrgRole.ADMIN
        is_teacher = classroom.teacher_id == user_id

        if not (is_owner or is_admin or is_teacher):
            student_stmt = select(ClassroomStudent).where(
                ClassroomStudent.classroom_id == classroom_id,
                ClassroomStudent.student_id == user_id,
            )
            is_student = (
                await session.execute(student_stmt)
            ).scalar_one_or_none() is not None
            if not is_student:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    # Conexão aceita após validação de handshake
    await websocket.accept()
    await connection_manager.connect(classroom_id, websocket)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                data = json.loads(raw_text)
                if isinstance(data, dict) and data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except (json.JSONDecodeError, TypeError) as json_err:
                logger.debug(
                    "Mensagem JSON inválida recebida no WebSocket: %s", json_err
                )
    except WebSocketDisconnect:
        logger.debug("WebSocket desconectado pelo cliente para a sala %s", classroom_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Erro na conexão WebSocket para a sala %s: %s", classroom_id, exc)
    finally:
        connection_manager.disconnect(classroom_id, websocket)
