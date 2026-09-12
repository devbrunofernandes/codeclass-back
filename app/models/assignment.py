import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssignmentType, ReleasePolicyType

if TYPE_CHECKING:
    from app.models.classroom import Classroom
    from app.models.submission import Submission


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    classroom_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("classrooms.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    type: Mapped[AssignmentType] = mapped_column(
        ENUM(AssignmentType, name="assignment_type", create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    release_policy: Mapped[ReleasePolicyType] = mapped_column(
        ENUM(ReleasePolicyType, name="release_policy_type", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=ReleasePolicyType.ON_REVIEW,
        server_default=text("'on_review'"),
        nullable=False,
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_assignments_class", "classroom_id"),
    )

    # Relationships
    classroom: Mapped[Classroom] = relationship(
        "Classroom",
        back_populates="assignments",
    )
    submissions: Mapped[list[Submission]] = relationship(
        "Submission",
        back_populates="assignment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Assignment id={self.id} title={self.title!r} type={self.type.value}>"
