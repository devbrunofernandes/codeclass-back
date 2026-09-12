import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import SubmissionStatus

if TYPE_CHECKING:
    from app.models.assignment import Assignment
    from app.models.user import User


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    ai_insights: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    grade: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        default=None,
    )
    status: Mapped[SubmissionStatus] = mapped_column(
        ENUM(SubmissionStatus, name="submission_status", create_type=False, values_callable=lambda x: [e.value for e in x]),
        default=SubmissionStatus.PENDING,
        server_default=text("'pending'"),
        nullable=False,
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id", name="uq_assignment_student"),
        Index("idx_submissions_assignment_status", assignment_id, status, submitted_at.desc()),
    )

    # Relationships
    assignment: Mapped[Assignment] = relationship(
        "Assignment",
        back_populates="submissions",
    )
    student: Mapped[User] = relationship(
        "User",
        back_populates="submissions",
    )
    evaluation: Mapped[SubmissionEvaluation | None] = relationship(
        "SubmissionEvaluation",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Submission id={self.id} assignment_id={self.assignment_id} student_id={self.student_id} status={self.status.value}>"


class SubmissionEvaluation(Base):
    __tablename__ = "submission_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("submissions.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    grade: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    general_feedback: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    detailed_scores: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=True,
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    submission: Mapped[Submission] = relationship(
        "Submission",
        back_populates="evaluation",
    )

    def __repr__(self) -> str:
        return f"<SubmissionEvaluation id={self.id} submission_id={self.submission_id} grade={self.grade}>"
