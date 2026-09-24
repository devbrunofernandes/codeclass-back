import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User


@dataclass
class TenantMember:
    user: User
    member: OrganizationMember
    token: str

    @property
    def auth_headers(self) -> dict[str, str]:
        """Header HTTP de autorização Bearer pronto para requisições."""
        return {"Authorization": f"Bearer {self.token}"}


@dataclass
class TenantContext:
    org: Organization
    owner: TenantMember
    admin: TenantMember
    teacher: TenantMember
    student: TenantMember
    other_teacher: TenantMember
    other_student: TenantMember


@pytest.fixture
async def create_tenant(
    db_session: AsyncSession,
    create_access_token: Callable[[uuid.UUID | str, str, str, timedelta | None], str],
) -> Callable[[str | None], Awaitable[TenantContext]]:
    """Factory flexível para instanciar tenants completos com membros e tokens."""

    async def _create(org_name: str | None = None) -> TenantContext:
        suffix = uuid.uuid4().hex[:6]
        name = org_name or f"Org {suffix}"
        slug = f"org-{suffix}"

        # 1. Usuários
        owner_id = uuid.uuid4()
        admin_id = uuid.uuid4()
        teacher_id = uuid.uuid4()
        student_id = uuid.uuid4()
        other_teacher_id = uuid.uuid4()
        other_student_id = uuid.uuid4()

        owner_u = User(
            id=owner_id, email=f"owner_{suffix}@test.com", full_name="Owner User"
        )
        admin_u = User(
            id=admin_id, email=f"admin_{suffix}@test.com", full_name="Admin User"
        )
        teacher_u = User(
            id=teacher_id, email=f"teacher_{suffix}@test.com", full_name="Teacher User"
        )
        student_u = User(
            id=student_id, email=f"student_{suffix}@test.com", full_name="Student User"
        )
        other_teacher_u = User(
            id=other_teacher_id,
            email=f"oteacher_{suffix}@test.com",
            full_name="Other Teacher",
        )
        other_student_u = User(
            id=other_student_id,
            email=f"ostudent_{suffix}@test.com",
            full_name="Other Student",
        )

        org = Organization(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            owner_id=owner_id,
        )

        db_session.add_all(
            [
                owner_u,
                admin_u,
                teacher_u,
                student_u,
                other_teacher_u,
                other_student_u,
                org,
            ]
        )
        await db_session.flush()

        # 2. Vínculos institucionais
        owner_m = OrganizationMember(
            organization_id=org.id, user_id=owner_id, role=OrgRole.OWNER
        )
        admin_m = OrganizationMember(
            organization_id=org.id, user_id=admin_id, role=OrgRole.ADMIN
        )
        teacher_m = OrganizationMember(
            organization_id=org.id, user_id=teacher_id, role=OrgRole.TEACHER
        )
        student_m = OrganizationMember(
            organization_id=org.id, user_id=student_id, role=OrgRole.STUDENT
        )
        other_teacher_m = OrganizationMember(
            organization_id=org.id, user_id=other_teacher_id, role=OrgRole.TEACHER
        )
        other_student_m = OrganizationMember(
            organization_id=org.id, user_id=other_student_id, role=OrgRole.STUDENT
        )

        db_session.add_all(
            [
                owner_m,
                admin_m,
                teacher_m,
                student_m,
                other_teacher_m,
                other_student_m,
            ]
        )
        await db_session.commit()

        # 3. Empacota com tokens JWT
        return TenantContext(
            org=org,
            owner=TenantMember(
                user=owner_u,
                member=owner_m,
                token=create_access_token(
                    owner_id, owner_u.email, owner_u.full_name, None
                ),
            ),
            admin=TenantMember(
                user=admin_u,
                member=admin_m,
                token=create_access_token(
                    admin_id, admin_u.email, admin_u.full_name, None
                ),
            ),
            teacher=TenantMember(
                user=teacher_u,
                member=teacher_m,
                token=create_access_token(
                    teacher_id, teacher_u.email, teacher_u.full_name, None
                ),
            ),
            student=TenantMember(
                user=student_u,
                member=student_m,
                token=create_access_token(
                    student_id, student_u.email, student_u.full_name, None
                ),
            ),
            other_teacher=TenantMember(
                user=other_teacher_u,
                member=other_teacher_m,
                token=create_access_token(
                    other_teacher_id,
                    other_teacher_u.email,
                    other_teacher_u.full_name,
                    None,
                ),
            ),
            other_student=TenantMember(
                user=other_student_u,
                member=other_student_m,
                token=create_access_token(
                    other_student_id,
                    other_student_u.email,
                    other_student_u.full_name,
                    None,
                ),
            ),
        )

    return _create


@pytest.fixture
async def tenant(
    create_tenant: Callable[[str | None], Awaitable[TenantContext]],
) -> TenantContext:
    """Fixture padrão que fornece um tenant completo pronto para uso imediato."""
    return await create_tenant(None)
