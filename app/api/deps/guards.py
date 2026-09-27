from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.api.deps.authentication import get_current_active_member
from app.api.deps.contexts import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
)
from app.api.deps.resolvers import (
    get_assignment_context,
    get_classroom_context,
    get_submission_context,
)
from app.core.exceptions import ForbiddenException
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember


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


require_owner = require_roles(OrgRole.OWNER)
require_admin_or_owner = require_roles(OrgRole.OWNER, OrgRole.ADMIN)
require_teacher = require_roles(OrgRole.TEACHER)
require_teacher_admin_or_owner = require_roles(
    OrgRole.OWNER, OrgRole.ADMIN, OrgRole.TEACHER
)


async def require_org_member(
    org_id: UUID,
    member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> OrganizationMember:
    """Garante que o membro pertence estritamente à organização indicada na rota."""
    if member.organization_id != org_id:
        raise ForbiddenException("Acesso negado a recursos de outra organização.")
    return member


# Alias de retrocompatibilidade para chamadas legadas
verify_org_access = require_org_member


def require_classroom_permission(
    *,
    can_manage: bool = False,
    can_manage_attachments: bool = False,
    can_view: bool = True,
    must_be_teacher: bool = False,
) -> Callable[..., ClassroomContext]:
    """Guard declarativo para autorização no contexto de sala de aula."""

    def dependency(
        context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    ) -> ClassroomContext:
        if must_be_teacher and not context.is_teacher_of_class:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala pode cadastrar atividades."
            )
        if can_manage_attachments and not context.can_manage_attachments:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala ou owner podem gerenciar materiais didáticos."
            )
        if can_manage and not context.can_manage_classroom:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável, administradores ou owner podem alterar esta sala."
            )
        if can_view and not context.can_view:
            raise ForbiddenException(
                "Acesso negado: você não é membro nem responsável por esta sala de aula."
            )
        return context

    return dependency


def require_assignment_permission(
    *,
    can_manage: bool = False,
    can_view: bool = True,
    must_be_enrolled_student: bool = False,
    must_be_teacher: bool = False,
    must_be_staff: bool = False,
) -> Callable[..., AssignmentContext]:
    """Guard declarativo para autorização no contexto de atividades.

    Args:
        can_manage: Exige que o membro seja o professor titular da turma da tarefa.
        can_view: Exige acesso para visualização da tarefa (equipe pedagógica ou aluno matriculado).
        must_be_enrolled_student: Exige que o membro seja um aluno formalmente matriculado na turma.
        must_be_teacher: Exige estritamente o professor responsável da turma.
        must_be_staff: Exige o professor da turma ou a coordenação institucional (Admin ou Owner).
    """

    def dependency(
        context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    ) -> AssignmentContext:
        if must_be_enrolled_student and not context.is_enrolled_student:
            raise ForbiddenException(
                "Acesso negado: apenas alunos matriculados na sala de aula podem realizar esta ação."
            )
        if must_be_teacher and not context.is_teacher_of_class:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala de aula pode realizar esta ação."
            )
        if must_be_staff and not (
            context.is_teacher_of_class or context.is_admin or context.is_owner
        ):
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala de aula ou administradores podem acessar este recurso."
            )
        if can_manage and not context.can_manage:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala pode editar esta atividade."
            )
        if can_view and not context.can_view:
            raise ForbiddenException(
                "Acesso negado: você não possui permissão para visualizar esta atividade."
            )
        return context

    return dependency


def require_submission_permission(
    *,
    can_view: bool = True,
    can_evaluate: bool = False,
    can_view_ai_insights: bool = False,
) -> Callable[..., SubmissionContext]:
    """Guard declarativo para autorização no contexto de submissões."""

    def dependency(
        context: Annotated[SubmissionContext, Depends(get_submission_context)],
    ) -> SubmissionContext:
        if can_evaluate and not context.can_evaluate:
            raise ForbiddenException(
                "Acesso negado: apenas o professor responsável pela sala de aula pode registrar avaliações."
            )
        if can_view_ai_insights and not context.can_view_ai_insights:
            raise ForbiddenException(
                "Acesso negado: apenas o docente responsável ou a coordenação podem solicitar nova avaliação da IA."
            )
        if can_view and not context.can_view:
            raise ForbiddenException(
                "Acesso negado: você não possui permissão para visualizar esta submissão."
            )
        return context

    return dependency
