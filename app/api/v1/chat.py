import json
import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from app.api.deps import (
    ClassroomContext,
    authenticate_classroom_connection,
    get_db,
    require_classroom_permission,
)
from app.core.database import async_session_maker
from app.infrastructure.realtime import connection_manager
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
    # Handshake: autenticação e autorização via helper agnóstico de protocolo
    async with async_session_maker() as session:
        try:
            await authenticate_classroom_connection(
                classroom_id=classroom_id,
                token=token,
                db=session,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Falha na autenticação do handshake WebSocket para a sala %s: %s",
                classroom_id,
                exc,
            )
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
