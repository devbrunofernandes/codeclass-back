from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.core.exceptions import (
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.services.auth_service import auth_service

security = HTTPBearer(auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = credentials.credentials
    payload = await auth_service.verify_jwt_token(token)

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedException("Token inválido: sujeito não encontrado.")

    try:
        user_id = UUID(str(sub))
    except (ValueError, TypeError) as e:
        raise UnauthorizedException(
            "Identificador de usuário inválido no token."
        ) from e

    # Consulta usuário no banco local
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("Usuário não encontrado.")

    return user


async def get_current_active_member(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMember:
    stmt = (
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization))
        .where(OrganizationMember.user_id == current_user.id)
    )
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()

    if member is None:
        raise ForbiddenException("Usuário não está vinculado a nenhuma organização.")

    if not member.is_active:
        raise ForbiddenException("Acesso de usuário desativado na organização.")

    return member


def require_roles(*allowed_roles: OrgRole) -> Callable[..., OrganizationMember]:
    """Dependência que exige um ou mais papéis RBAC específicos."""

    def role_checker(
        member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    ) -> OrganizationMember:
        if member.role not in allowed_roles:
            raise ForbiddenException(
                "Acesso negado: permissão insuficiente para executar esta ação."
            )
        return member

    return role_checker


async def verify_org_access(
    org_id: UUID,
    member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> OrganizationMember:
    """Garante que o membro pertence estritamente à organização indicada na rota (RNF01)."""
    if member.organization_id != org_id:
        raise ForbiddenException("Acesso negado a recursos de outra organização.")
    return member


require_owner = require_roles(OrgRole.OWNER)
require_admin_or_owner = require_roles(OrgRole.OWNER, OrgRole.ADMIN)
require_teacher = require_roles(OrgRole.TEACHER)
require_teacher_admin_or_owner = require_roles(
    OrgRole.OWNER, OrgRole.ADMIN, OrgRole.TEACHER
)


@dataclass
class ClassroomContext:
    classroom: Classroom
    current_member: OrganizationMember
    is_owner: bool
    is_admin: bool
    is_teacher_of_class: bool
    is_enrolled_student: bool

    @property
    def can_manage_classroom(self) -> bool:
        return self.is_owner or self.is_admin or self.is_teacher_of_class

    @property
    def can_manage_attachments(self) -> bool:
        return self.is_owner or self.is_teacher_of_class

    @property
    def can_view(self) -> bool:
        return self.can_manage_classroom or self.is_enrolled_student


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

    if classroom.organization_id != current_member.organization_id:
        raise ForbiddenException("Acesso negado a recursos de outra organização.")

    is_owner = current_member.role == OrgRole.OWNER
    is_admin = current_member.role == OrgRole.ADMIN
    is_teacher_of_class = classroom.teacher_id == current_member.user_id

    # Checa se o usuário é aluno matriculado
    enrolled_stmt = select(ClassroomStudent).where(
        ClassroomStudent.classroom_id == classroom_id,
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


@dataclass
class AssignmentContext:
    assignment: Assignment
    classroom: Classroom
    current_member: OrganizationMember
    is_owner: bool
    is_admin: bool
    is_teacher_of_class: bool
    is_enrolled_student: bool

    @property
    def can_view(self) -> bool:
        return (
            self.is_owner
            or self.is_admin
            or self.is_teacher_of_class
            or self.is_enrolled_student
        )

    @property
    def can_manage(self) -> bool:
        return self.is_teacher_of_class


async def get_assignment_context(
    assignment_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentContext:
    """Carrega a atividade e valida isolamento de tenant e privilégios contextuais."""
    stmt = (
        select(Assignment)
        .options(selectinload(Assignment.classroom))
        .where(Assignment.id == assignment_id)
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()

    if assignment is None:
        raise NotFoundException("Atividade não encontrada.")

    classroom = assignment.classroom
    if classroom.organization_id != current_member.organization_id:
        raise ForbiddenException("Acesso negado a recursos de outra organização.")

    is_owner = current_member.role == OrgRole.OWNER
    is_admin = current_member.role == OrgRole.ADMIN
    is_teacher_of_class = classroom.teacher_id == current_member.user_id

    # Checa se o usuário é aluno matriculado na turma da atividade
    enrolled_stmt = select(ClassroomStudent).where(
        ClassroomStudent.classroom_id == classroom.id,
        ClassroomStudent.student_id == current_member.user_id,
    )
    enrolled_res = await db.execute(enrolled_stmt)
    is_enrolled_student = enrolled_res.scalar_one_or_none() is not None

    return AssignmentContext(
        assignment=assignment,
        classroom=classroom,
        current_member=current_member,
        is_owner=is_owner,
        is_admin=is_admin,
        is_teacher_of_class=is_teacher_of_class,
        is_enrolled_student=is_enrolled_student,
    )


__all__ = [
    "AssignmentContext",
    "AsyncGenerator",
    "AsyncSession",
    "ClassroomContext",
    "get_assignment_context",
    "get_classroom_context",
    "get_current_active_member",
    "get_current_user",
    "get_db",
    "require_admin_or_owner",
    "require_owner",
    "require_roles",
    "require_teacher",
    "require_teacher_admin_or_owner",
    "verify_org_access",
]
