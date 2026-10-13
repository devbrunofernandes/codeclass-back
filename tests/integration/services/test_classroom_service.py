import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
)
from app.models.classroom import Classroom
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.services.classroom_service import classroom_service


@pytest.mark.asyncio
async def test_classroom_service_create_invalid_teacher(
    db_session: AsyncSession,
) -> None:
    # Arrange
    org_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    other_owner_id = uuid.uuid4()
    teacher_id = uuid.uuid4()

    owner = User(id=owner_id, email="owner@service.com", full_name="Owner")
    other_owner = User(
        id=other_owner_id, email="other_owner@service.com", full_name="Other Owner"
    )
    teacher = User(id=teacher_id, email="teacher@service.com", full_name="Teacher")

    org = Organization(id=org_id, name="Org", slug="org-svc", owner_id=owner_id)
    other_org = Organization(
        id=other_org_id,
        name="Other Org",
        slug="other-org-svc",
        owner_id=other_owner_id,
    )

    owner_member = OrganizationMember(
        organization_id=org_id, user_id=owner_id, role=OrgRole.OWNER
    )
    other_owner_member = OrganizationMember(
        organization_id=other_org_id, user_id=other_owner_id, role=OrgRole.OWNER
    )
    # Teacher vinculado a outra organização
    other_member = OrganizationMember(
        organization_id=other_org_id, user_id=teacher_id, role=OrgRole.TEACHER
    )

    db_session.add_all(
        [
            owner,
            other_owner,
            teacher,
            org,
            other_org,
            owner_member,
            other_owner_member,
            other_member,
        ]
    )
    await db_session.commit()

    # Act & Assert
    # Tentativa de indicar docente de outra organização -> NotFoundException
    with pytest.raises(NotFoundException) as exc:
        await classroom_service.create_classroom(
            organization_id=org_id,
            name="Sala Inválida",
            description=None,
            teacher_id=teacher_id,
            creator_member=owner_member,
            db=db_session,
        )
    assert exc.value.status_code == 404
    assert "professor indicado não pertence a esta organização" in exc.value.message


@pytest.mark.asyncio
async def test_classroom_service_enroll_non_student_or_other_org(
    db_session: AsyncSession,
) -> None:
    # Arrange
    org_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    teacher = User(id=teacher_id, email="prof@svc.com", full_name="Prof")
    admin = User(id=admin_id, email="admin@svc.com", full_name="Admin")
    org = Organization(id=org_id, name="Org", slug="org-svc2", owner_id=teacher_id)
    t_member = OrganizationMember(
        organization_id=org_id, user_id=teacher_id, role=OrgRole.TEACHER
    )
    # Usuário é ADMIN, não STUDENT
    a_member = OrganizationMember(
        organization_id=org_id, user_id=admin_id, role=OrgRole.ADMIN
    )
    classroom = Classroom(
        id=uuid.uuid4(),
        organization_id=org_id,
        teacher_id=teacher_id,
        name="Turma Teste",
    )

    db_session.add_all([teacher, admin, org, t_member, a_member, classroom])
    await db_session.commit()

    # Act & Assert
    # Tenta matricular usuário que é ADMIN e não STUDENT -> BadRequestException
    with pytest.raises(BadRequestException) as exc:
        await classroom_service.enroll_student(
            classroom=classroom,
            student_id=admin_id,
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "papel de estudante" in exc.value.message
