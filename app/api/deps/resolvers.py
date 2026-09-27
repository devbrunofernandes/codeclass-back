from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.authentication import get_current_active_member
from app.api.deps.contexts import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
)
from app.api.deps.database import get_db
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.submission import Submission


async def _build_classroom_context(
    classroom: Classroom,
    current_member: OrganizationMember,
    db: AsyncSession,
) -> ClassroomContext:
    """Constrói ClassroomContext validando isolamento de tenant e status de matrícula."""
    if classroom.organization_id != current_member.organization_id:
        raise ForbiddenException("Acesso negado a recursos de outra organização.")

    is_owner = current_member.role == OrgRole.OWNER
    is_admin = current_member.role == OrgRole.ADMIN
    is_teacher_of_class = classroom.teacher_id == current_member.user_id

    enrolled_stmt = select(ClassroomStudent).where(
        ClassroomStudent.classroom_id == classroom.id,
        ClassroomStudent.student_id == current_member.user_id,
    )
    enrolled_res = await db.execute(enrolled_stmt)
    is_enrolled_student = enrolled_res.scalar_one_or_none() is not None

    return ClassroomContext(
        classroom=classroom,
        current_member=current_member,
        is_owner=is_owner,
        is_admin=is_admin,
        is_teacher_of_class=is_teacher_of_class,
        is_enrolled_student=is_enrolled_student,
    )


async def get_classroom_context(
    classroom_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomContext:
    """Carrega a sala de aula e valida o isolamento de tenant e privilégios do membro."""
    stmt = (
        select(Classroom)
        .options(selectinload(Classroom.teacher))
        .where(Classroom.id == classroom_id)
    )
    result = await db.execute(stmt)
    classroom = result.scalar_one_or_none()

    if classroom is None:
        raise NotFoundException("Sala de aula não encontrada.")

    return await _build_classroom_context(classroom, current_member, db)


async def get_assignment_context(
    assignment_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentContext:
    """Carrega a atividade e valida isolamento de tenant compondo ClassroomContext."""
    stmt = (
        select(Assignment)
        .options(selectinload(Assignment.classroom).selectinload(Classroom.teacher))
        .where(Assignment.id == assignment_id)
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()

    if assignment is None:
        raise NotFoundException("Atividade não encontrada.")

    classroom_context = await _build_classroom_context(
        assignment.classroom, current_member, db
    )
    return AssignmentContext(
        assignment=assignment,
        classroom_context=classroom_context,
    )


async def get_submission_context(
    submission_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionContext:
    """Carrega a submissão e valida isolamento compondo AssignmentContext e ClassroomContext."""
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.assignment)
            .selectinload(Assignment.classroom)
            .selectinload(Classroom.teacher),
            selectinload(Submission.student),
            selectinload(Submission.ai_insight),
            selectinload(Submission.evaluation),
        )
        .where(Submission.id == submission_id)
    )
    result = await db.execute(stmt)
    submission = result.scalar_one_or_none()

    if submission is None:
        raise NotFoundException("Submissão não encontrada.")

    classroom_context = await _build_classroom_context(
        submission.assignment.classroom, current_member, db
    )
    assignment_context = AssignmentContext(
        assignment=submission.assignment,
        classroom_context=classroom_context,
    )
    is_submission_author = submission.student_id == current_member.user_id

    return SubmissionContext(
        submission=submission,
        assignment_context=assignment_context,
        is_submission_author=is_submission_author,
    )
