from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClassroomCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=255)
    description: str | None = None
    teacher_id: UUID | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ClassroomUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class ClassroomTeacherResponse(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class ClassroomResponse(BaseModel):
    id: UUID
    organization_id: UUID
    teacher_id: UUID
    name: str
    description: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClassroomDetailResponse(ClassroomResponse):
    teacher: ClassroomTeacherResponse
    total_students: int


class ClassroomMyClassResponse(ClassroomResponse):
    role_in_class: Literal["teacher", "student", "owner", "admin"]


class EnrollStudentRequest(BaseModel):
    student_id: UUID


class ClassroomStudentMemberResponse(BaseModel):
    student_id: UUID
    full_name: str
    email: EmailStr
    enrolled_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClassroomMembersResponse(BaseModel):
    teacher: ClassroomTeacherResponse
    students: list[ClassroomStudentMemberResponse]


class ClassroomAttachmentResponse(BaseModel):
    file_name: str
    file_path: str
    size_bytes: int
    content_type: str | None = None
    uploaded_at: datetime | None = None


class ClassroomAttachmentDownloadResponse(BaseModel):
    file_name: str
    download_url: str
    expires_in: int
