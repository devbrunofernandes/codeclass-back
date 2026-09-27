from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AssignmentContext,
    ClassroomContext,
    get_assignment_context,
    get_classroom_context,
    get_db,
)
from app.core.exceptions import ForbiddenException
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentStudentResponse,
    AssignmentTeacherResponse,
    AssignmentUpdateRequest,
)
from app.schemas.runner import TestRunRequest, TestRunResponse
from app.services.assignment_service import assignment_service
from app.services.runner_service import runner_service

router = APIRouter()


@router.post(
    "/classrooms/{classroom_id}/assignments",
    response_model=AssignmentTeacherResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria tarefa (código ou questionário) com rubricas e gabaritos",
)
async def create_assignment(
    request: AssignmentCreateRequest,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentTeacherResponse:
    if not context.is_teacher_of_class:
        raise ForbiddenException(
            "Acesso negado: apenas o professor responsável pela sala pode cadastrar atividades."
        )

    assignment = await assignment_service.create_assignment(
        context.classroom, request, db
    )
    return AssignmentTeacherResponse.model_validate(assignment)


@router.get(
    "/classrooms/{classroom_id}/assignments",
    response_model=list[AssignmentTeacherResponse | AssignmentStudentResponse],
    summary="Lista todas as atividades da turma com sanitização para alunos",
)
async def list_assignments(
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AssignmentTeacherResponse | AssignmentStudentResponse]:
    if not context.can_view:
        raise ForbiddenException(
            "Acesso negado: você não é membro nem responsável por esta sala de aula."
        )

    assignments = await assignment_service.list_assignments_by_classroom(
        context.classroom.id, db
    )
    return assignment_service.serialize_assignments_for_member(
        assignments, is_student=context.is_enrolled_student
    )


@router.get(
    "/assignments/{assignment_id}",
    response_model=AssignmentTeacherResponse | AssignmentStudentResponse,
    summary="Consulta detalhes da atividade com proteção contra vazamento de gabaritos",
)
async def get_assignment(
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
) -> AssignmentTeacherResponse | AssignmentStudentResponse:
    if not context.can_view:
        raise ForbiddenException(
            "Acesso negado: você não possui permissão para visualizar esta atividade."
        )

    return assignment_service.serialize_assignment_for_member(
        context.assignment, is_student=context.is_enrolled_student
    )


@router.patch(
    "/assignments/{assignment_id}",
    response_model=AssignmentTeacherResponse,
    summary="Atualiza prazo, enunciados ou configurações da tarefa",
)
async def update_assignment(
    request: AssignmentUpdateRequest,
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssignmentTeacherResponse:
    if not context.can_manage:
        raise ForbiddenException(
            "Acesso negado: apenas o professor responsável pela sala pode editar esta atividade."
        )

    updated = await assignment_service.update_assignment(
        context.assignment, request, db
    )
    return AssignmentTeacherResponse.model_validate(updated)


@router.delete(
    "/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui atividade (bloqueado se houver submissões ativas)",
)
async def delete_assignment(
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    if not context.can_manage:
        raise ForbiddenException(
            "Acesso negado: apenas o professor responsável pela sala pode excluir esta atividade."
        )

    await assignment_service.delete_assignment(context.assignment, db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/assignments/{assignment_id}/test-run",
    response_model=TestRunResponse,
    status_code=status.HTTP_200_OK,
    summary="Executa código experimental via Code Runner contra casos de teste (efêmero)",
)
async def test_run_assignment(
    request: TestRunRequest,
    context: Annotated[AssignmentContext, Depends(get_assignment_context)],
) -> TestRunResponse:
    if not context.can_view:
        raise ForbiddenException(
            "Acesso negado: você não possui permissão para executar código nesta atividade."
        )

    return await runner_service.execute_test_run(
        assignment=context.assignment,
        request=request,
    )
