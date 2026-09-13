from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import OrgRole
from app.schemas.user import UserCreate

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SlugType = Annotated[
    str,
    Field(min_length=3, max_length=100, pattern=SLUG_PATTERN),
]


class OrganizationRegisterRequest(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    slug: SlugType
    owner: UserCreate


class OrganizationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=255)
    slug: SlugType | None = None


class OrganizationResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=6)
    role: OrgRole


class OrganizationMemberResponse(BaseModel):
    organization_id: UUID
    user_id: UUID
    email: EmailStr
    full_name: str
    role: OrgRole
    is_active: bool
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemberRoleUpdateRequest(BaseModel):
    role: OrgRole


class MemberStatusUpdateRequest(BaseModel):
    is_active: bool


class TransferOwnershipRequest(BaseModel):
    new_owner_id: UUID


class ClassroomSummaryResponse(BaseModel):
    id: UUID
    organization_id: UUID
    teacher_id: UUID
    name: str
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
