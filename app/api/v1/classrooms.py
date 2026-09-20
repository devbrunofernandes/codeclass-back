import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import (
    ClassroomContext,
    get_classroom_context,
    get_current_active_member,
    get_db,
)
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.classroom import (
    ClassroomAttachmentDownloadResponse,
    ClassroomAttachmentResponse,
    ClassroomDetailResponse,
    ClassroomMembersResponse,
    ClassroomMyClassResponse,
    ClassroomResponse,
    ClassroomStudentMemberResponse,
    ClassroomTeacherResponse,
    ClassroomUpdateRequest,
    EnrollStudentRequest,
)
from app.services.storage_service import StorageError, storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classrooms")


@router.get(
    "/my-classes",
    response_model=list[ClassroomMyClassResponse],
    summary="Lista turmas do usuário logado (Professor, Aluno ou Coordenação)",
)
async def list_my_classrooms(
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ClassroomMyClassResponse]:
    """Retorna as turmas em que o usuário atua como professor ou está matriculado como aluno."""
    # Se for Owner ou Admin, traz todas as turmas da instituição
    if current_member.role in (OrgRole.OWNER, OrgRole.ADMIN):
        stmt = (
            select(Classroom)
            .where(Classroom.organization_id == current_member.organization_id)
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        classrooms = result.scalars().all()
        role_str: Literal["owner", "admin"] = (
            "owner" if current_member.role == OrgRole.OWNER else "admin"
        )
        return [
            ClassroomMyClassResponse(
                id=c.id,
                organization_id=c.organization_id,
                teacher_id=c.teacher_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at,
                role_in_class="teacher"
                if c.teacher_id == current_member.user_id
                else role_str,
            )
            for c in classrooms
        ]

    # Se for professor: turmas que leciona
    if current_member.role == OrgRole.TEACHER:
        stmt = (
            select(Classroom)
            .where(
                Classroom.organization_id == current_member.organization_id,
                Classroom.teacher_id == current_member.user_id,
            )
            .order_by(Classroom.created_at.desc())
        )
        result = await db.execute(stmt)
        teaching = result.scalars().all()
        return [
            ClassroomMyClassResponse(
                id=c.id,
                organization_id=c.organization_id,
                teacher_id=c.teacher_id,
                name=c.name,
                description=c.description,
                created_at=c.created_at,
                role_in_class="teacher",
            )
            for c in teaching
        ]

    # Se for aluno: turmas onde está matriculado
    stmt_student = (
        select(Classroom)
        .join(ClassroomStudent, Classroom.id == ClassroomStudent.classroom_id)
        .where(
            Classroom.organization_id == current_member.organization_id,
            ClassroomStudent.student_id == current_member.user_id,
        )
        .order_by(Classroom.created_at.desc())
    )
    result_student = await db.execute(stmt_student)
    enrolled = result_student.scalars().all()
    return [
        ClassroomMyClassResponse(
            id=c.id,
            organization_id=c.organization_id,
            teacher_id=c.teacher_id,
            name=c.name,
            description=c.description,
            created_at=c.created_at,
            role_in_class="student",
        )
        for c in enrolled
    ]


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não é membro nem responsável por esta sala de aula.",
        )

    classroom = context.classroom

    # Contagem de alunos matriculados
    count_stmt = (
        select(func.count())
        .select_from(ClassroomStudent)
        .where(ClassroomStudent.classroom_id == classroom.id)
    )
    total_students = (await db.execute(count_stmt)).scalar() or 0

    return ClassroomDetailResponse(
        id=classroom.id,
        organization_id=classroom.organization_id,
        teacher_id=classroom.teacher_id,
        name=classroom.name,
        description=classroom.description,
        created_at=classroom.created_at,
        teacher=ClassroomTeacherResponse(
            id=classroom.teacher.id,
            full_name=classroom.teacher.full_name,
            email=classroom.teacher.email,
        ),
        total_students=total_students,
    )


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: apenas o professor responsável, administradores ou owner podem alterar esta sala.",
        )

    classroom = context.classroom
    if request.name is not None:
        classroom.name = request.name
    if request.description is not None:
        classroom.description = request.description

    await db.commit()
    await db.refresh(classroom)
    return ClassroomResponse.model_validate(classroom)


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: permissão insuficiente para excluir esta sala de aula.",
        )

    await db.delete(context.classroom)
    await db.commit()
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: apenas o professor responsável ou coordenação podem matricular alunos.",
        )

    # Verifica se o usuário é membro ativo da mesma organização e tem papel de student
    member_stmt = (
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.user))
        .where(
            OrganizationMember.organization_id == context.classroom.organization_id,
            OrganizationMember.user_id == request.student_id,
        )
    )
    member_res = await db.execute(member_stmt)
    student_member = member_res.scalar_one_or_none()

    if student_member is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O usuário indicado não pertence a esta organização.",
        )

    if not student_member.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível matricular um usuário desativado na organização.",
        )

    if student_member.role != OrgRole.STUDENT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas membros com papel de estudante podem ser matriculados na turma.",
        )

    # Verifica se já está matriculado
    enrolled_stmt = select(ClassroomStudent).where(
        ClassroomStudent.classroom_id == context.classroom.id,
        ClassroomStudent.student_id == request.student_id,
    )
    enrolled_res = await db.execute(enrolled_stmt)
    if enrolled_res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O estudante já está matriculado nesta turma.",
        )

    new_enrollment = ClassroomStudent(
        classroom_id=context.classroom.id,
        student_id=request.student_id,
    )
    db.add(new_enrollment)
    try:
        await db.commit()
        await db.refresh(new_enrollment)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O estudante já está matriculado nesta turma.",
        )

    return ClassroomStudentMemberResponse(
        student_id=student_member.user.id,
        full_name=student_member.user.full_name,
        email=student_member.user.email,
        enrolled_at=new_enrollment.enrolled_at,
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: permissão insuficiente para desmatricular alunos desta sala.",
        )

    enrolled_stmt = select(ClassroomStudent).where(
        ClassroomStudent.classroom_id == context.classroom.id,
        ClassroomStudent.student_id == student_id,
    )
    enrolled_res = await db.execute(enrolled_stmt)
    enrollment = enrolled_res.scalar_one_or_none()

    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O estudante não está matriculado nesta turma.",
        )

    await db.delete(enrollment)
    await db.commit()
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não possui permissão para visualizar os membros desta sala.",
        )

    classroom = context.classroom
    teacher_resp = ClassroomTeacherResponse(
        id=classroom.teacher.id,
        full_name=classroom.teacher.full_name,
        email=classroom.teacher.email,
    )

    stmt = (
        select(ClassroomStudent, User)
        .join(User, ClassroomStudent.student_id == User.id)
        .where(ClassroomStudent.classroom_id == classroom.id)
        .order_by(ClassroomStudent.enrolled_at.asc())
    )
    results = (await db.execute(stmt)).all()

    students_resp = [
        ClassroomStudentMemberResponse(
            student_id=user.id,
            full_name=user.full_name,
            email=user.email,
            enrolled_at=enrollment.enrolled_at,
        )
        for enrollment, user in results
    ]

    return ClassroomMembersResponse(teacher=teacher_resp, students=students_resp)


# --- Materiais Didáticos e Anexos (Supabase Storage) ---


@router.post(
    "/{classroom_id}/attachments",
    response_model=ClassroomAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload em streaming de material didático (máx. 30MB)",
)
async def upload_attachment(
    file: UploadFile,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
) -> ClassroomAttachmentResponse:
    if not context.can_manage_attachments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: apenas o professor responsável pela sala ou owner podem anexar materiais didáticos.",
        )

    try:
        data = await storage_service.upload_classroom_material(
            organization_id=context.classroom.organization_id,
            classroom_id=context.classroom.id,
            file=file,
        )
    except StorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return ClassroomAttachmentResponse(
        file_name=data["file_name"],
        file_path=data["file_path"],
        size_bytes=data["size_bytes"],
        content_type=data["content_type"],
    )


@router.get(
    "/{classroom_id}/attachments",
    response_model=list[ClassroomAttachmentResponse],
    summary="Lista metadados dos materiais anexados no Supabase Storage",
)
async def list_attachments(
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
) -> list[ClassroomAttachmentResponse]:
    if not context.can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não é membro desta sala.",
        )

    try:
        files = await storage_service.list_classroom_materials(
            organization_id=context.classroom.organization_id,
            classroom_id=context.classroom.id,
        )
    except StorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return [
        ClassroomAttachmentResponse(
            file_name=f["file_name"],
            file_path=f["file_path"],
            size_bytes=f["size_bytes"],
            content_type=f["content_type"],
            uploaded_at=f["uploaded_at"],
        )
        for f in files
    ]


@router.get(
    "/{classroom_id}/attachments/{file_name}/download",
    response_model=ClassroomAttachmentDownloadResponse,
    summary="Retorna Signed URL temporária do Supabase Storage para download direto",
)
async def get_attachment_download_url(
    file_name: str,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
) -> ClassroomAttachmentDownloadResponse:
    if not context.can_view:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não é membro desta sala.",
        )

    try:
        download_url = await storage_service.create_signed_download_url(
            organization_id=context.classroom.organization_id,
            classroom_id=context.classroom.id,
            file_name=file_name,
            expires_in=3600,
        )
    except StorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return ClassroomAttachmentDownloadResponse(
        file_name=file_name,
        download_url=download_url,
        expires_in=3600,
    )


@router.delete(
    "/{classroom_id}/attachments/{file_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui arquivo de apoio do Supabase Storage",
)
async def delete_attachment(
    file_name: str,
    context: Annotated[ClassroomContext, Depends(get_classroom_context)],
) -> Response:
    if not context.can_manage_attachments:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: apenas o professor responsável pela sala ou owner podem remover materiais didáticos.",
        )

    try:
        await storage_service.delete_classroom_material(
            organization_id=context.classroom.organization_id,
            classroom_id=context.classroom.id,
            file_name=file_name,
        )
    except StorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    return Response(status_code=status.HTTP_204_NO_CONTENT)
