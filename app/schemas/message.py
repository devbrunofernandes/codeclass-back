from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrgRole


class ChatMessageSenderResponse(BaseModel):
    id: UUID
    full_name: str
    role: OrgRole

    model_config = ConfigDict(from_attributes=True)


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(str_strip_whitespace=True)


class ChatMessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(str_strip_whitespace=True)


class ChatMessageResponse(BaseModel):
    id: UUID
    classroom_id: UUID
    sender: ChatMessageSenderResponse
    content: str
    is_edited: bool
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageDeletedEvent(BaseModel):
    type: Literal["message_deleted"] = "message_deleted"
    message_id: UUID
    classroom_id: UUID


class ChatMessageWebSocketEvent(BaseModel):
    type: Literal["new_message", "message_edited"]
    data: ChatMessageResponse
