import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.enums import OrgRole
from app.schemas.message import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatMessageSenderResponse,
    ChatMessageUpdate,
    ChatMessageWebSocketEvent,
    MessageDeletedEvent,
)


def test_chat_message_create_valid() -> None:
    schema = ChatMessageCreate(content="  Olá mundo!  ")
    assert schema.content == "Olá mundo!"


def test_chat_message_create_empty_fails() -> None:
    with pytest.raises(ValidationError):
        ChatMessageCreate(content="")

    with pytest.raises(ValidationError):
        ChatMessageCreate(content="   ")


def test_chat_message_create_too_long_fails() -> None:
    with pytest.raises(ValidationError):
        ChatMessageCreate(content="a" * 5001)


def test_chat_message_update_valid() -> None:
    schema = ChatMessageUpdate(content="  Texto corrigido  ")
    assert schema.content == "Texto corrigido"


def test_chat_message_update_empty_fails() -> None:
    with pytest.raises(ValidationError):
        ChatMessageUpdate(content="")


def test_chat_message_sender_response() -> None:
    sender = ChatMessageSenderResponse(
        id=uuid.uuid4(),
        full_name="Alan Turing",
        role=OrgRole.STUDENT,
    )
    assert sender.role == OrgRole.STUDENT
    assert sender.full_name == "Alan Turing"


def test_chat_message_response_serialization() -> None:
    msg_id = uuid.uuid4()
    room_id = uuid.uuid4()
    sender_id = uuid.uuid4()
    now = datetime.now(UTC)

    response = ChatMessageResponse(
        id=msg_id,
        classroom_id=room_id,
        sender=ChatMessageSenderResponse(
            id=sender_id,
            full_name="Ada Lovelace",
            role=OrgRole.TEACHER,
        ),
        content="Aviso sobre a prova.",
        is_edited=False,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump()
    assert data["id"] == msg_id
    assert data["classroom_id"] == room_id
    assert data["sender"]["role"] == "teacher"
    assert data["content"] == "Aviso sobre a prova."
    assert not data["is_edited"]
    assert not data["is_deleted"]


def test_message_deleted_event() -> None:
    msg_id = uuid.uuid4()
    room_id = uuid.uuid4()
    event = MessageDeletedEvent(message_id=msg_id, classroom_id=room_id)
    assert event.type == "message_deleted"
    assert event.message_id == msg_id
    assert event.classroom_id == room_id


def test_chat_message_websocket_event() -> None:
    msg_id = uuid.uuid4()
    room_id = uuid.uuid4()
    now = datetime.now(UTC)
    resp = ChatMessageResponse(
        id=msg_id,
        classroom_id=room_id,
        sender=ChatMessageSenderResponse(
            id=uuid.uuid4(),
            full_name="User",
            role=OrgRole.STUDENT,
        ),
        content="Teste",
        is_edited=True,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )

    ws_event = ChatMessageWebSocketEvent(type="message_edited", data=resp)
    assert ws_event.type == "message_edited"
    assert ws_event.data.is_edited is True
