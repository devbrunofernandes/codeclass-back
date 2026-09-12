import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.chat import ClassroomMessage
    from app.models.organization import Organization
    from app.models.user import User


class Classroom(Base):
    __tablename__ = "classrooms"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_classrooms_org", "organization_id"),
        Index("idx_classrooms_teacher", "teacher_id"),
    )

    # Relationships
    organization: Mapped[Organization] = relationship(
        "Organization",
        back_populates="classrooms",
    )
    teacher: Mapped[User] = relationship(
        "User",
        back_populates="teaching_classrooms",
        foreign_keys=[teacher_id],
    )
    students: Mapped[list[ClassroomStudent]] = relationship(
        "ClassroomStudent",
        back_populates="classroom",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    assignments: Mapped[list[Assignment]] = relationship(
        "Assignment",
        back_populates="classroom",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    messages: Mapped[list[ClassroomMessage]] = relationship(
        "ClassroomMessage",
        back_populates="classroom",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Classroom id={self.id} name={self.name!r} org_id={self.organization_id}>"


class ClassroomStudent(Base):
    __tablename__ = "classroom_students"

    classroom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        primary_key=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_classroom_students_student", "student_id"),
    )

    # Relationships
    classroom: Mapped[Classroom] = relationship(
        "Classroom",
        back_populates="students",
    )
    student: Mapped[User] = relationship(
        "User",
        back_populates="enrolled_classrooms",
    )

    def __repr__(self) -> str:
        return f"<ClassroomStudent classroom_id={self.classroom_id} student_id={self.student_id}>"
