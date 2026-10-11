from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.organization import OrganizationMember
from app.models.submission import Submission
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentStudentResponse,
    AssignmentTeacherResponse,
    AssignmentUpdateRequest,
    CodeAssignmentConfig,
    QuestionnaireAssignmentConfig,
    StudentAssignmentFilterStatus,
    StudentAssignmentItemResponse,
    StudentAssignmentsSummaryResponse,
    StudentAssignmentStatus,
    StudentAssignmentSubmissionBrief,
)


class AssignmentService:
    async def create_assignment(
        self, classroom: Classroom, request: AssignmentCreateRequest, db: AsyncSession
    ) -> Assignment:
        """Cria e persiste uma nova atividade para a sala de aula."""
        config_data = (
            request.config.model_dump()
            if hasattr(request.config, "model_dump")
            else request.config
        )

        assignment = Assignment(
            classroom_id=classroom.id,
            title=request.title,
            description=request.description,
            type=request.type,
            release_policy=request.release_policy,
            deadline=request.deadline,
            config=config_data,
        )
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        return assignment

    async def list_assignments_by_classroom(
        self, classroom_id: UUID, db: AsyncSession
    ) -> list[Assignment]:
        """Lista todas as atividades cadastradas em uma turma."""
        stmt = (
            select(Assignment)
            .where(Assignment.classroom_id == classroom_id)
            .order_by(Assignment.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def update_assignment(
        self,
        assignment: Assignment,
        request: AssignmentUpdateRequest,
        db: AsyncSession,
    ) -> Assignment:
        effective_policy = (
            request.release_policy
            if request.release_policy is not None
            else assignment.release_policy
        )
        effective_config = assignment.config
        if request.config is not None:
            raw_cfg = (
                request.config.model_dump()
                if hasattr(request.config, "model_dump")
                else request.config
            )
            if assignment.type == AssignmentType.CODE:
                CodeAssignmentConfig.model_validate(raw_cfg)
            elif assignment.type == AssignmentType.QUESTIONNAIRE:
                QuestionnaireAssignmentConfig.model_validate(raw_cfg)
            effective_config = raw_cfg
            assignment.config = raw_cfg

        if effective_policy == ReleasePolicyType.IMMEDIATE:
            if assignment.type == AssignmentType.CODE:
                raise BadRequestException(
                    "A política de liberação imediata ('immediate') não é permitida para atividades de código, pois exigem avaliação docente."
                )
            if assignment.type == AssignmentType.QUESTIONNAIRE:
                questions = effective_config.get("questions", [])
                if any(q.get("type") == "open" for q in questions):
                    raise BadRequestException(
                        "A política de liberação imediata ('immediate') é restrita a questionários 100% objetivos (sem questões dissertativas)."
                    )

        if request.title is not None:
            assignment.title = request.title
        if request.description is not None:
            assignment.description = request.description
        if request.release_policy is not None:
            assignment.release_policy = request.release_policy
        if "deadline" in request.model_fields_set:
            assignment.deadline = request.deadline

        await db.commit()
        await db.refresh(assignment)
        return assignment

    async def delete_assignment(self, assignment: Assignment, db: AsyncSession) -> None:
        """Exclui a atividade caso não possua submissões vinculadas."""
        stmt = select(func.count(Submission.id)).where(
            Submission.assignment_id == assignment.id
        )
        count = await db.scalar(stmt)
        if count and count > 0:
            raise BadRequestException(
                "Não é possível excluir a atividade pois já existem submissões vinculadas."
            )

        await db.delete(assignment)
        await db.commit()

    def serialize_assignment_for_member(
        self, assignment: Assignment, is_student: bool
    ) -> AssignmentTeacherResponse | AssignmentStudentResponse:
        """Serializa a atividade segregando gabaritos e rubricas caso o membro seja estudante."""
        if is_student:
            return AssignmentStudentResponse.model_validate(assignment)
        return AssignmentTeacherResponse.model_validate(assignment)

    def serialize_assignments_for_member(
        self, assignments: list[Assignment], is_student: bool
    ) -> list[AssignmentTeacherResponse | AssignmentStudentResponse]:
        """Serializa uma lista de atividades aplicando a política pedagógica de sanitização."""
        return [
            self.serialize_assignment_for_member(a, is_student) for a in assignments
        ]

    async def _validate_student_classroom_access(
        self, member: OrganizationMember, classroom_id: UUID, db: AsyncSession
    ) -> Classroom:
        """Valida que a sala de aula existe na organização e que o aluno está nela matriculado."""
        stmt = select(Classroom).where(Classroom.id == classroom_id)
        classroom = (await db.execute(stmt)).scalar_one_or_none()
        if classroom is None:
            raise NotFoundException("Sala de aula não encontrada.")
        if classroom.organization_id != member.organization_id:
            raise ForbiddenException("Acesso negado a recursos de outra organização.")

        enrolled_stmt = select(ClassroomStudent).where(
            ClassroomStudent.classroom_id == classroom_id,
            ClassroomStudent.student_id == member.user_id,
        )
        enrolled = (await db.execute(enrolled_stmt)).scalar_one_or_none()
        if enrolled is None:
            raise ForbiddenException(
                "Acesso negado: você não é membro nem responsável por esta sala de aula."
            )
        return classroom

    async def list_student_assignments(
        self,
        member: OrganizationMember,
        classroom_id: UUID | None,
        status_filter: StudentAssignmentFilterStatus | None,
        db: AsyncSession,
    ) -> list[StudentAssignmentItemResponse]:
        """Lista atividades do estudante calculando dinamicamente o status discente."""
        if classroom_id is not None:
            await self._validate_student_classroom_access(member, classroom_id, db)

        stmt = (
            select(Assignment, Classroom.name, Submission)
            .join(Classroom, Assignment.classroom_id == Classroom.id)
            .join(ClassroomStudent, ClassroomStudent.classroom_id == Classroom.id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id)
                & (Submission.student_id == member.user_id),
            )
            .where(
                Classroom.organization_id == member.organization_id,
                ClassroomStudent.student_id == member.user_id,
            )
            .order_by(Assignment.created_at.desc())
        )

        if classroom_id is not None:
            stmt = stmt.where(Assignment.classroom_id == classroom_id)

        result = await db.execute(stmt)
        rows = result.all()

        now = datetime.now(UTC)
        items: list[StudentAssignmentItemResponse] = []

        for assignment, classroom_name, submission in rows:
            is_overdue = False
            if assignment.deadline is not None:
                deadline = (
                    assignment.deadline
                    if assignment.deadline.tzinfo
                    else assignment.deadline.replace(tzinfo=UTC)
                )
                is_overdue = now > deadline

            has_draft = False
            submission_brief: StudentAssignmentSubmissionBrief | None = None

            if submission is None:
                student_status = (
                    StudentAssignmentStatus.OVERDUE
                    if is_overdue
                    else StudentAssignmentStatus.PENDING
                )
            elif submission.status == SubmissionStatus.DRAFT:
                has_draft = True
                student_status = (
                    StudentAssignmentStatus.OVERDUE
                    if is_overdue
                    else StudentAssignmentStatus.PENDING
                )
            elif submission.status == SubmissionStatus.PUBLISHED:
                student_status = StudentAssignmentStatus.GRADED
                submission_brief = StudentAssignmentSubmissionBrief.model_validate(
                    submission
                )
            else:
                student_status = StudentAssignmentStatus.SUBMITTED
                submission_brief = StudentAssignmentSubmissionBrief.model_validate(
                    submission
                )

            # Filtro por status
            if status_filter is not None:
                if status_filter == StudentAssignmentFilterStatus.UNSUBMITTED:
                    if student_status not in (
                        StudentAssignmentStatus.PENDING,
                        StudentAssignmentStatus.OVERDUE,
                    ):
                        continue
                elif student_status.value != status_filter.value:
                    continue

            items.append(
                StudentAssignmentItemResponse(
                    id=assignment.id,
                    classroom_id=assignment.classroom_id,
                    classroom_name=classroom_name,
                    title=assignment.title,
                    description=assignment.description,
                    type=assignment.type,
                    release_policy=assignment.release_policy,
                    deadline=assignment.deadline,
                    created_at=assignment.created_at,
                    student_status=student_status,
                    has_draft=has_draft,
                    submission=submission_brief,
                )
            )

        return items

    async def get_student_assignments_summary(
        self,
        member: OrganizationMember,
        classroom_id: UUID | None,
        db: AsyncSession,
    ) -> StudentAssignmentsSummaryResponse:
        """Computa contadores sumarizados de tarefas para o estudante."""
        all_items = await self.list_student_assignments(
            member=member,
            classroom_id=classroom_id,
            status_filter=None,
            db=db,
        )

        counts = {
            "total": len(all_items),
            "pending": 0,
            "overdue": 0,
            "submitted": 0,
            "graded": 0,
        }

        for item in all_items:
            counts[item.student_status.value] += 1

        return StudentAssignmentsSummaryResponse(**counts)


assignment_service = AssignmentService()
