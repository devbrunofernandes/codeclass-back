import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.chat import ClassroomMessage
    from app.models.classroom import Classroom, ClassroomStudent
    from app.models.organization import Organization, OrganizationMember
    from app.models.submission import Submission


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    owned_organization: Mapped[Organization | None] = relationship(
        "Organization",
        back_populates="owner",
        foreign_keys="[Organization.owner_id]",
        uselist=False,
    )
    membership: Mapped[OrganizationMember | None] = relationship(
        "OrganizationMember",
        back_populates="user",
        uselist=False,
        passive_deletes=True,
    )
    teaching_classrooms: Mapped[list[Classroom]] = relationship(
        "Classroom",
        back_populates="teacher",
        foreign_keys="[Classroom.teacher_id]",
    )
    enrolled_classrooms: Mapped[list[ClassroomStudent]] = relationship(
        "ClassroomStudent",
        back_populates="student",
        passive_deletes=True,
    )
    submissions: Mapped[list[Submission]] = relationship(
        "Submission",
        back_populates="student",
        passive_deletes=True,
    )
    messages: Mapped[list[ClassroomMessage]] = relationship(
        "ClassroomMessage",
        back_populates="sender",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} full_name={self.full_name!r}>"
