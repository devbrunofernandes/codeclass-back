from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AssignmentContext, get_assignment_context, get_db
from app.core.exceptions import ForbiddenException
from app.schemas.submission import (
    SubmissionCreateRequest,
    SubmissionStudentResponse,
)
from app.services.submission_service import submission_service

router = APIRouter()


@router.post(
    "/assignments/{assignment_id}/submissions",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria ou reenvia submissão formal de atividade (código ou questionário)",
)
async def submit_assignment(
    request: SubmissionCreateRequest,
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStudentResponse:
    if not context.is_enrolled_student:
        raise ForbiddenException(
            "Acesso negado: apenas alunos matriculados na sala de aula podem submeter atividades."
        )

    sub = await submission_service.submit_assignment(
        context.assignment, context.current_member.user_id, request, db
    )
    return SubmissionStudentResponse.model_validate(sub)


@router.post(
    "/assignments/{assignment_id}/submissions/unsubmit",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Desfaz entrega formal no prazo, preservando o conteúdo e transitando para draft",
)
async def unsubmit_assignment(
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStudentResponse:
    if not context.is_enrolled_student:
        raise ForbiddenException(
            "Acesso negado: apenas alunos matriculados na sala de aula podem desfazer entregas."
        )

    sub = await submission_service.unsubmit_assignment(
        context.assignment, context.current_member.user_id, db
    )
    return SubmissionStudentResponse.model_validate(sub)


@router.get(
    "/assignments/{assignment_id}/submissions/me",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta a entrega atual ou rascunho do próprio estudante autenticado",
)
async def get_my_submission(
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStudentResponse:
    if not context.is_enrolled_student:
        raise ForbiddenException(
            "Acesso negado: apenas alunos matriculados na sala de aula podem consultar suas entregas."
        )

    sub = await submission_service.get_my_submission(
        context.assignment, context.current_member.user_id, db
    )
    return SubmissionStudentResponse.model_validate(sub)
