from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ClassroomContext,
    get_classroom_context,
    get_current_active_member,
    get_db,
)
from app.api.v1 import classroom_attachments
from app.core.exceptions import ForbiddenException
from app.models.organization import OrganizationMember
from app.schemas.classroom import (
    ClassroomDetailResponse,
    ClassroomMembersResponse,
    ClassroomMyClassResponse,
    ClassroomResponse,
    ClassroomStudentMemberResponse,
    ClassroomUpdateRequest,
    EnrollStudentRequest,
)
from app.services.classroom_service import classroom_service

router = APIRouter(prefix="/classrooms")

# Sub-roteador especializado em materiais didáticos e anexos (Opção B)
router.include_router(classroom_attachments.router)


@router.get(
    "/my-classes",
    response_model=list[ClassroomMyClassResponse],
    summary="Lista turmas do usuário logado (Professor, Aluno ou Coordenação)",
)
async def list_my_classrooms(
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ClassroomMyClassResponse]:
    """Retorna as turmas do usuário despachando a consulta via Strategy Pattern conforme seu papel."""
    return await classroom_service.list_user_classrooms(current_member, db)


@router.get(
    "/{classroom_id}",
    response_model=ClassroomDetailResponse,
    summary="Consulta detalhes completos da sala de aula",
)
async def get_classroom_details(
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomDetailResponse:
    if not context.can_view:
        raise ForbiddenException(
            "Acesso negado: você não é membro nem responsável por esta sala de aula."
        )

    return await classroom_service.get_classroom_details(context.classroom, db)


@router.patch(
    "/{classroom_id}",
    response_model=ClassroomResponse,
    summary="Atualiza nome ou descrição da sala de aula",
)
async def update_classroom(
    request: ClassroomUpdateRequest,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomResponse:
    if not context.can_manage_classroom:
        raise ForbiddenException(
            "Acesso negado: apenas o professor responsável, administradores ou owner podem alterar esta sala."
        )

    updated = await classroom_service.update_classroom(
        context.classroom, request.name, request.description, db
    )
    return ClassroomResponse.model_validate(updated)


@router.delete(
    "/{classroom_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Encerra ou remove a sala de aula",
)
async def delete_classroom(
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    if not context.can_manage_classroom:
        raise ForbiddenException(
            "Acesso negado: permissão insuficiente para excluir esta sala de aula."
        )

    await classroom_service.delete_classroom(context.classroom, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Matrículas e Membros da Sala ---


@router.post(
    "/{classroom_id}/students",
    response_model=ClassroomStudentMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Matricula aluno existente na organização dentro da sala",
)
async def enroll_student(
    request: EnrollStudentRequest,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomStudentMemberResponse:
    if not context.can_manage_classroom:
        raise ForbiddenException(
            "Acesso negado: apenas o professor responsável ou coordenação podem matricular alunos."
        )

    return await classroom_service.enroll_student(
        context.classroom, request.student_id, db
    )


@router.delete(
    "/{classroom_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desvincula aluno da sala de aula",
)
async def unenroll_student(
    student_id: UUID,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    if not context.can_manage_classroom:
        raise ForbiddenException(
            "Acesso negado: permissão insuficiente para desmatricular alunos desta sala."
        )

    await classroom_service.unenroll_student(context.classroom.id, student_id, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{classroom_id}/members",
    response_model=ClassroomMembersResponse,
    summary="Lista o professor responsável e os alunos matriculados na turma",
)
@router.get(
    "/{classroom_id}/students",
    response_model=ClassroomMembersResponse,
    include_in_schema=False,
    summary="Alias de compatibilidade retroativa para consulta de membros da turma",
)
async def list_classroom_members(
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomMembersResponse:
    if not context.can_view:
        raise ForbiddenException(
            "Acesso negado: você não possui permissão para visualizar os membros desta sala."
        )

    return await classroom_service.list_classroom_members(context.classroom, db)
