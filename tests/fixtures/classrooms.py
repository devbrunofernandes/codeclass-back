import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.classroom import Classroom, ClassroomStudent
from tests.fixtures.tenants import TenantContext


@pytest.fixture
def create_classroom(
    db_session: AsyncSession,
) -> Callable[[TenantContext, uuid.UUID | None, str | None], Awaitable[Classroom]]:
    """Factory flexível para instanciar turmas personalizadas associadas a um tenant."""

    async def _create(
        tenant: TenantContext,
        teacher_id: uuid.UUID | None = None,
        name: str | None = None,
    ) -> Classroom:
        c = Classroom(
            id=uuid.uuid4(),
            organization_id=tenant.org.id,
            teacher_id=teacher_id or tenant.teacher.user.id,
            name=name or "Turma de Algoritmos e Estruturas de Dados",
        )
        db_session.add(c)
        await db_session.commit()
        return c

    return _create


@pytest.fixture
async def classroom(
    tenant: TenantContext,
    create_classroom: Callable[
        [TenantContext, uuid.UUID | None, str | None], Awaitable[Classroom]
    ],
) -> Classroom:
    """Fixture que cria uma turma vinculada ao professor principal do tenant."""
    return await create_classroom(tenant)


@pytest.fixture
async def enrolled_student(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
) -> ClassroomStudent:
    """Fixture que matricula o aluno principal do tenant na turma."""
    cs = ClassroomStudent(
        classroom_id=classroom.id,
        student_id=tenant.student.user.id,
    )
    db_session.add(cs)
    await db_session.commit()
    return cs


@pytest.fixture
async def classroom_with_student(
    classroom: Classroom, enrolled_student: ClassroomStudent
) -> Classroom:
    """Fixture composta que garante uma turma com aluno já matriculado."""
    return classroom
