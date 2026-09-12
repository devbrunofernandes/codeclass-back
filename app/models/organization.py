import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import OrgRole

if TYPE_CHECKING:
    from app.models.classroom import Classroom
    from app.models.user import User


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_organizations_owner", "owner_id"),
    )

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        back_populates="owned_organization",
        foreign_keys=[owner_id],
    )
    members: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    classrooms: Mapped[list[Classroom]] = relationship(
        "Classroom",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r} name={self.name!r}>"


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        unique=True,
    )
    role: Mapped[OrgRole] = mapped_column(
        ENUM(OrgRole, name="org_role", create_type=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    organization: Mapped[Organization] = relationship(
        "Organization",
        back_populates="members",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="membership",
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember org_id={self.organization_id} user_id={self.user_id} role={self.role.value}>"
