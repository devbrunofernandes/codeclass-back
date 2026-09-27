from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
    get_current_active_member,
    get_db,
    require_assignment_permission,
    require_classroom_permission,
    require_submission_permission,
)
from app.models.enums import OrgRole, SubmissionStatus
from app.models.organization import OrganizationMember
from app.schemas.evaluation import (
    BatchEvaluationReleaseRequest,
    BatchEvaluationReleaseResponse,
    SubmissionEvaluationRequest,
    SubmissionEvaluationResponse,
)
from app.schemas.submission import (
    SubmissionCreateRequest,
    SubmissionDetailStudentResponse,
    SubmissionDetailTeacherResponse,
    SubmissionDraftRequest,
    SubmissionStatsResponse,
    SubmissionStudentResponse,
    SubmissionSummaryStudentResponse,
    SubmissionSummaryTeacherResponse,
)
from app.services.submission import (
    submission_ai_worker,
    submission_evaluation_service,
    submission_lifecycle_service,
    submission_query_service,
)

router = APIRouter()


@router.post(
    "/assignments/{assignment_id}/submissions",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria ou reenvia submissão formal de atividade (código ou questionário)",
)
async def submit_assignment(
    request: SubmissionCreateRequest,
    context: Annotated[
        AssignmentContext,
        Depends(require_assignment_permission(must_be_enrolled_student=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> SubmissionStudentResponse:
    sub = await submission_lifecycle_service.submit_assignment(
        context.assignment,
        context.current_member.user_id,
        request,
        db,
        background_tasks=background_tasks,
    )
    return SubmissionStudentResponse.model_validate(sub)


@router.post(
    "/assignments/{assignment_id}/submissions/unsubmit",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Desfaz entrega formal no prazo, preservando o conteúdo e transitando para draft",
)
async def unsubmit_assignment(
    context: Annotated[
        AssignmentContext,
        Depends(require_assignment_permission(must_be_enrolled_student=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStudentResponse:
    sub = await submission_lifecycle_service.unsubmit_assignment(
        context.assignment, context.current_member.user_id, db
    )
    return SubmissionStudentResponse.model_validate(sub)


@router.put(
    "/assignments/{assignment_id}/submissions/draft",
    response_model=SubmissionStudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Salva ou atualiza rascunho de submissão do aluno sem submissão formal nem disparo de IA",
)
async def save_draft_submission(
    request: SubmissionDraftRequest,
    context: Annotated[
        AssignmentContext,
        Depends(require_assignment_permission(must_be_enrolled_student=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStudentResponse:
    sub = await submission_lifecycle_service.save_draft_submission(
        assignment=context.assignment,
        student_id=context.current_member.user_id,
        request=request,
        db=db,
    )
    return SubmissionStudentResponse.model_validate(sub)


@router.get(
    "/submissions",
    response_model=list[
        SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse
    ],
    status_code=status.HTTP_200_OK,
    summary="Lista submissões em âmbito global na organização com filtros avançados",
)
async def list_global_submissions(
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
    classroom_id: Annotated[
        UUID | None,
        Query(description="Filtrar por sala de aula específica"),
    ] = None,
    assignment_id: Annotated[
        UUID | None,
        Query(description="Filtrar por atividade específica"),
    ] = None,
    submission_status: Annotated[
        SubmissionStatus | None,
        Query(alias="status", description="Filtrar por status da submissão"),
    ] = None,
    student_id: Annotated[
        UUID | None,
        Query(
            description="Filtrar por estudante específico (apenas docentes/coordenação)"
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="Filtrar por nome ou e-mail do estudante (apenas docentes/coordenação)"
        ),
    ] = None,
) -> list[SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse]:
    is_student = current_member.role == OrgRole.STUDENT
    is_teacher = current_member.role == OrgRole.TEACHER

    student_id_filter: UUID | None = (
        current_member.user_id if is_student else student_id
    )
    enrolled_student_id: UUID | None = current_member.user_id if is_student else None
    teacher_id: UUID | None = current_member.user_id if is_teacher else None
    search_filter: str | None = None if is_student else q

    submissions = await submission_query_service.list_submissions(
        assignment_id=assignment_id,
        status_filter=submission_status,
        db=db,
        classroom_id=classroom_id,
        organization_id=current_member.organization_id,
        student_id=student_id_filter,
        search_query=search_filter,
        teacher_id=teacher_id,
        enrolled_student_id=enrolled_student_id,
    )
    if is_student:
        return [SubmissionSummaryStudentResponse.model_validate(s) for s in submissions]
    return [SubmissionSummaryTeacherResponse.model_validate(s) for s in submissions]


@router.get(
    "/classrooms/{classroom_id}/submissions",
    response_model=list[
        SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse
    ],
    status_code=status.HTTP_200_OK,
    summary="Lista submissões da sala de aula com filtros por status, estudante ou busca textual",
)
async def list_classroom_submissions(
    context: Annotated[
        ClassroomContext, Depends(require_classroom_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    submission_status: Annotated[
        SubmissionStatus | None,
        Query(alias="status", description="Filtrar por status da submissão"),
    ] = None,
    student_id: Annotated[
        UUID | None,
        Query(
            description="Filtrar por estudante específico (apenas docentes/coordenação)"
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="Filtrar por nome ou e-mail do estudante (apenas docentes/coordenação)"
        ),
    ] = None,
) -> list[SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse]:
    is_staff = context.can_manage_classroom
    student_id_filter: UUID | None = (
        student_id if is_staff else context.current_member.user_id
    )
    search_query_filter: str | None = q if is_staff else None

    submissions = await submission_query_service.list_submissions(
        classroom_id=context.classroom.id,
        status_filter=submission_status,
        student_id=student_id_filter,
        search_query=search_query_filter,
        organization_id=context.classroom.organization_id,
        db=db,
    )
    if is_staff:
        return [SubmissionSummaryTeacherResponse.model_validate(s) for s in submissions]
    return [SubmissionSummaryStudentResponse.model_validate(s) for s in submissions]


@router.get(
    "/assignments/{assignment_id}/submissions",
    response_model=list[
        SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse
    ],
    status_code=status.HTTP_200_OK,
    summary="Lista submissões da tarefa com filtros por status, estudante ou termo de busca",
)
async def list_submissions(
    context: Annotated[
        AssignmentContext, Depends(require_assignment_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    submission_status: Annotated[
        SubmissionStatus | None,
        Query(alias="status", description="Filtrar por status da submissão"),
    ] = None,
    student_id: Annotated[
        UUID | None,
        Query(
            description="Filtrar por estudante específico (apenas docentes/coordenação)"
        ),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="Filtrar por nome ou e-mail do estudante (apenas docentes/coordenação)"
        ),
    ] = None,
) -> list[SubmissionSummaryTeacherResponse | SubmissionSummaryStudentResponse]:
    is_staff = context.is_teacher_of_class or context.is_admin or context.is_owner
    student_id_filter: UUID | None = (
        student_id if is_staff else context.current_member.user_id
    )
    search_query_filter: str | None = q if is_staff else None

    submissions = await submission_query_service.list_submissions(
        assignment_id=context.assignment.id,
        status_filter=submission_status,
        student_id=student_id_filter,
        search_query=search_query_filter,
        db=db,
    )
    if is_staff:
        return [SubmissionSummaryTeacherResponse.model_validate(s) for s in submissions]
    return [SubmissionSummaryStudentResponse.model_validate(s) for s in submissions]


@router.get(
    "/submissions/{submission_id}",
    response_model=SubmissionDetailTeacherResponse | SubmissionDetailStudentResponse,
    status_code=status.HTTP_200_OK,
    summary="Detalha submissão para docentes e alunos (com segregação estrita de IA e retenção de notas)",
)
async def get_submission(
    context: Annotated[
        SubmissionContext, Depends(require_submission_permission(can_view=True))
    ],
) -> SubmissionDetailTeacherResponse | SubmissionDetailStudentResponse:
    return submission_query_service.get_submission_detail(
        context.submission,
        can_view_ai_insights=context.can_view_ai_insights,
    )


@router.post(
    "/submissions/{submission_id}/retry-ai",
    response_model=SubmissionDetailTeacherResponse,
    status_code=status.HTTP_200_OK,
    summary="Reinicia a análise assíncrona de IA para uma submissão",
)
async def retry_ai_evaluation(
    context: Annotated[
        SubmissionContext,
        Depends(require_submission_permission(can_view_ai_insights=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    background_tasks: BackgroundTasks,
) -> SubmissionDetailTeacherResponse:
    sub = await submission_ai_worker.retry_ai_evaluation(
        submission=context.submission,
        db=db,
        background_tasks=background_tasks,
    )
    return SubmissionDetailTeacherResponse.model_validate(sub)


@router.put(
    "/submissions/{submission_id}/evaluation",
    response_model=SubmissionEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Registra ou atualiza a avaliação docente formal de uma submissão",
)
async def evaluate_submission(
    request: SubmissionEvaluationRequest,
    context: Annotated[
        SubmissionContext,
        Depends(require_submission_permission(can_evaluate=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionEvaluationResponse:
    evaluation = await submission_evaluation_service.evaluate_submission(
        submission=context.submission,
        request=request,
        db=db,
    )
    return SubmissionEvaluationResponse.model_validate(evaluation)


@router.get(
    "/submissions/{submission_id}/evaluation",
    response_model=SubmissionEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="Consulta a avaliação formal realizada pelo professor (notas e parecer autoral)",
)
async def get_submission_evaluation(
    context: Annotated[
        SubmissionContext, Depends(require_submission_permission(can_view=True))
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionEvaluationResponse:
    is_teacher_or_admin = (
        context.is_teacher_of_class or context.is_admin or context.is_owner
    )
    evaluation = await submission_evaluation_service.get_submission_evaluation(
        submission=context.submission,
        is_teacher_or_admin=is_teacher_or_admin,
        is_author=context.is_submission_author,
        db=db,
    )
    return SubmissionEvaluationResponse.model_validate(evaluation)


@router.post(
    "/assignments/{assignment_id}/submissions/publish-evaluations",
    response_model=BatchEvaluationReleaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Publica em lote avaliações com correção já registrada na tarefa (todas ou seletivas)",
)
async def publish_assignment_evaluations(
    context: Annotated[
        AssignmentContext,
        Depends(require_assignment_permission(must_be_teacher=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: BatchEvaluationReleaseRequest | None = None,
) -> BatchEvaluationReleaseResponse:
    submission_ids = request.submission_ids if request else None
    count = await submission_evaluation_service.publish_assignment_evaluations(
        assignment_id=context.assignment.id,
        db=db,
        submission_ids=submission_ids,
    )
    return BatchEvaluationReleaseResponse(
        assignment_id=context.assignment.id,
        published_count=count,
        message=f"{count} correção(ões) publicada(s) com sucesso aos alunos.",
    )


@router.get(
    "/assignments/{assignment_id}/submissions/stats",
    response_model=SubmissionStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtém métricas executivas de correção e engajamento da tarefa",
)
async def get_assignment_submission_stats(
    context: Annotated[
        AssignmentContext,
        Depends(require_assignment_permission(must_be_staff=True)),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SubmissionStatsResponse:
    return await submission_query_service.get_assignment_submission_stats(
        assignment=context.assignment,
        db=db,
    )
