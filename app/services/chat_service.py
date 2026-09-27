import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.infrastructure.realtime import connection_manager
from app.models.chat import ClassroomMessage
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.message import (
    ChatMessageResponse,
    ChatMessageSenderResponse,
    MessageDeletedEvent,
)


class ChatService:
    """Serviço de domínio para o chat da sala de aula com suporte a tempo real."""

    def to_response(self, msg: ClassroomMessage) -> ChatMessageResponse:
        """Converte o modelo ORM ClassroomMessage para o schema ChatMessageResponse."""
        sender_role = (
            msg.sender.membership.role
            if msg.sender and msg.sender.membership
            else OrgRole.STUDENT
        )
        content = "[Esta mensagem foi apagada]" if msg.is_deleted else msg.content
        return ChatMessageResponse(
            id=msg.id,
            classroom_id=msg.classroom_id,
            sender=ChatMessageSenderResponse(
                id=msg.sender.id,
                full_name=msg.sender.full_name,
                role=sender_role,
            ),
            content=content,
            is_edited=msg.is_edited,
            is_deleted=msg.is_deleted,
            created_at=msg.created_at,
            updated_at=msg.updated_at,
        )

    async def list_messages(
        self,
        classroom_id: uuid.UUID,
        limit: int = 50,
        before: datetime | None = None,
        db: AsyncSession | None = None,
    ) -> list[ClassroomMessage]:
        """Consulta o histórico de mensagens da turma com suporte a paginação cronológica."""
        if db is None:
            raise ValueError("AsyncSession é obrigatória.")

        stmt = (
            select(ClassroomMessage)
            .options(
                selectinload(ClassroomMessage.sender).selectinload(User.membership)
            )
            .where(
                ClassroomMessage.classroom_id == classroom_id,
            )
        )
        if before is not None:
            stmt = stmt.where(ClassroomMessage.created_at < before)

        stmt = stmt.order_by(ClassroomMessage.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        messages = list(result.scalars().all())

        # Inverte para retornar em ordem cronológica (antigas primeiro)
        messages.reverse()
        return messages

    async def send_message(
        self,
        classroom_id: uuid.UUID,
        sender_id: uuid.UUID,
        content: str,
        db: AsyncSession,
    ) -> ClassroomMessage:
        """Persiste nova mensagem e distribui broadcast via WebSocket."""
        msg = ClassroomMessage(
            classroom_id=classroom_id,
            sender_id=sender_id,
            content=content,
        )
        db.add(msg)
        await db.commit()

        # Recarrega a mensagem com o sender e seu papel
        stmt = (
            select(ClassroomMessage)
            .options(
                selectinload(ClassroomMessage.sender).selectinload(User.membership)
            )
            .where(ClassroomMessage.id == msg.id)
        )
        loaded_msg = (await db.execute(stmt)).scalar_one()

        # Broadcast via WebSocket
        response_schema = self.to_response(loaded_msg)
        ws_payload = {
            "type": "new_message",
            "data": response_schema.model_dump(mode="json"),
        }
        await connection_manager.broadcast(classroom_id, ws_payload)
        return loaded_msg

    async def edit_message(
        self,
        classroom_id: uuid.UUID,
        message_id: uuid.UUID,
        user_id: uuid.UUID,
        content: str,
        db: AsyncSession,
    ) -> ClassroomMessage:
        """Edita mensagem do autor respeitando a janela de tolerância de 15 minutos."""
        stmt = (
            select(ClassroomMessage)
            .options(
                selectinload(ClassroomMessage.sender).selectinload(User.membership)
            )
            .where(
                ClassroomMessage.id == message_id,
                ClassroomMessage.classroom_id == classroom_id,
            )
        )
        result = await db.execute(stmt)
        msg = result.scalar_one_or_none()

        if msg is None:
            raise NotFoundException("Mensagem não encontrada.")

        if msg.is_deleted:
            raise BadRequestException("Mensagens excluídas não podem ser editadas.")

        if msg.sender_id != user_id:
            raise ForbiddenException("Apenas o autor pode editar esta mensagem.")

        # Validação da janela temporal de 15 minutos
        now = datetime.now(UTC)
        msg_created_at = msg.created_at
        if msg_created_at.tzinfo is None:
            msg_created_at = msg_created_at.replace(tzinfo=UTC)

        if now - msg_created_at > timedelta(minutes=15):
            raise BadRequestException(
                "O prazo limite de 15 minutos para edição da mensagem expirou."
            )

        msg.content = content
        msg.is_edited = True
        await db.commit()
        await db.refresh(msg)

        # Broadcast via WebSocket
        response_schema = self.to_response(msg)
        ws_payload = {
            "type": "message_edited",
            "data": response_schema.model_dump(mode="json"),
        }
        await connection_manager.broadcast(classroom_id, ws_payload)
        return msg

    async def delete_message(
        self,
        classroom_id: uuid.UUID,
        message_id: uuid.UUID,
        member: OrganizationMember,
        is_teacher_of_class: bool,
        db: AsyncSession,
    ) -> ClassroomMessage:
        """Marca mensagem como excluída respeitando moderação e tolerância de 15 min."""
        stmt = (
            select(ClassroomMessage)
            .options(
                selectinload(ClassroomMessage.sender).selectinload(User.membership)
            )
            .where(
                ClassroomMessage.id == message_id,
                ClassroomMessage.classroom_id == classroom_id,
            )
        )
        result = await db.execute(stmt)
        msg = result.scalar_one_or_none()

        if msg is None:
            raise NotFoundException("Mensagem não encontrada.")

        if msg.is_deleted:
            raise BadRequestException("Mensagem já foi excluída.")

        # Permissão de moderação irrestrita para Admin, Owner e Professor da turma
        is_moderator = (
            member.role in (OrgRole.OWNER, OrgRole.ADMIN) or is_teacher_of_class
        )

        if not is_moderator:
            if msg.sender_id != member.user_id:
                raise ForbiddenException(
                    "Apenas o autor ou moderadores da sala podem excluir esta mensagem."
                )

            # Se for o próprio autor comum, valida tolerância de 15 minutos
            now = datetime.now(UTC)
            msg_created_at = msg.created_at
            if msg_created_at.tzinfo is None:
                msg_created_at = msg_created_at.replace(tzinfo=UTC)

            if now - msg_created_at > timedelta(minutes=15):
                raise BadRequestException(
                    "O prazo limite de 15 minutos para exclusão da mensagem expirou."
                )

        msg.is_deleted = True
        await db.commit()
        await db.refresh(msg)

        # Broadcast via WebSocket
        event = MessageDeletedEvent(message_id=msg.id, classroom_id=classroom_id)
        await connection_manager.broadcast(classroom_id, event.model_dump(mode="json"))
        return msg


chat_service = ChatService()
