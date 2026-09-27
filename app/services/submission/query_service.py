import uuid
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import SubmissionStatus
from app.models.submission import Submission
from app.models.user import User
from app.schemas.evaluation import SubmissionEvaluationResponse
from app.schemas.submission import (
    SubmissionAiInsightResponse,
    SubmissionAssignmentInfo,
    SubmissionDetailStudentResponse,
    SubmissionDetailTeacherResponse,
    SubmissionStatsResponse,
    SubmissionStudentInfo,
)


class SubmissionQueryService:
    """Serviço de consulta, filtros avançados, estatísticas e projeção de detalhes de submissões."""

    async def list_submissions(
        self,
        assignment_id: uuid.UUID | None = None,
        status_filter: SubmissionStatus | None = None,
        db: AsyncSession | None = None,
        *,
        classroom_id: uuid.UUID | None = None,
        organization_id: uuid.UUID | None = None,
        student_id: uuid.UUID | None = None,
        search_query: str | None = None,
        teacher_id: uuid.UUID | None = None,
        enrolled_student_id: uuid.UUID | None = None,
    ) -> list[Submission]:
        """Lista as submissões com suporte a filtros globais, por sala, atividade, status, aluno e busca textual."""
        if db is None:
            raise ValueError("Database session is required")

        stmt = (
            select(Submission)
            .join(Submission.assignment)
            .join(Assignment.classroom)
            .options(
                selectinload(Submission.assignment),
                selectinload(Submission.student),
                selectinload(Submission.ai_insight),
                selectinload(Submission.evaluation),
            )
        )

        if organization_id:
            stmt = stmt.where(Classroom.organization_id == organization_id)
        if classroom_id:
            stmt = stmt.where(Assignment.classroom_id == classroom_id)
        if assignment_id:
            stmt = stmt.where(Submission.assignment_id == assignment_id)
        if teacher_id:
            stmt = stmt.where(Classroom.teacher_id == teacher_id)
        if enrolled_student_id:
            stmt = stmt.where(
                Classroom.id.in_(
                    select(ClassroomStudent.classroom_id).where(
                        ClassroomStudent.student_id == enrolled_student_id
                    )
                )
            )
        if student_id:
            stmt = stmt.where(Submission.student_id == student_id)
        if status_filter:
            stmt = stmt.where(Submission.status == status_filter)
        if search_query and search_query.strip():
            term = f"%{search_query.strip()}%"
            stmt = stmt.join(Submission.student).where(
                or_(User.full_name.ilike(term), User.email.ilike(term))
            )

        stmt = stmt.order_by(Submission.submitted_at.desc())
        result = await db.execute(stmt)
        return list(result.scalars().all())

    def get_submission_detail(
        self,
        submission: Submission,
        can_view_ai_insights: bool | None = None,
        is_student: bool | None = None,
    ) -> SubmissionDetailTeacherResponse | SubmissionDetailStudentResponse:
        """Serializa os detalhes da submissão com segregação estrita de IA (omitida para estudantes) e retenção de avaliação."""
        if can_view_ai_insights is None:
            can_view_ai_insights = not (is_student if is_student is not None else False)

        assignment_info = SubmissionAssignmentInfo.model_validate(submission.assignment)

        if can_view_ai_insights:
            ai_insight = None
            evaluation = None
            if submission.ai_insight:
                ai_insight = SubmissionAiInsightResponse.model_validate(
                    submission.ai_insight
                )
            if submission.evaluation:
                evaluation = SubmissionEvaluationResponse.model_validate(
                    submission.evaluation
                )

            return SubmissionDetailTeacherResponse(
                id=submission.id,
                assignment=assignment_info,
                student=SubmissionStudentInfo.model_validate(submission.student),
                content=submission.content,
                grade=submission.grade,
                status=submission.status,
                submitted_at=submission.submitted_at,
                ai_insight=ai_insight,
                evaluation=evaluation,
            )

        # Estudante: o schema nem sequer possui o campo ai_insight (segregação por design)
        evaluation_student = None
        if submission.status == SubmissionStatus.PUBLISHED and submission.evaluation:
            evaluation_student = SubmissionEvaluationResponse.model_validate(
                submission.evaluation
            )

        return SubmissionDetailStudentResponse(
            id=submission.id,
            assignment=assignment_info,
            student=SubmissionStudentInfo.model_validate(submission.student),
            content=submission.content,
            grade=submission.grade,
            status=submission.status,
            submitted_at=submission.submitted_at,
            evaluation=evaluation_student,
        )

    async def get_assignment_submission_stats(
        self,
        assignment: Assignment,
        db: AsyncSession,
    ) -> SubmissionStatsResponse:
        """Calcula métricas executivas de correção e engajamento da tarefa."""
        # 1. Total de alunos matriculados na turma
        enrolled_stmt = select(func.count(ClassroomStudent.student_id)).where(
            ClassroomStudent.classroom_id == assignment.classroom_id
        )
        total_enrolled = (await db.execute(enrolled_stmt)).scalar() or 0

        # 2. Submissões da atividade
        subs_stmt = (
            select(Submission)
            .options(selectinload(Submission.evaluation))
            .where(Submission.assignment_id == assignment.id)
        )
        subs_result = await db.execute(subs_stmt)
        submissions = subs_result.scalars().all()

        total_submissions = len(submissions)
        pending = 0
        awaiting_review = 0
        ready_to_publish = 0
        published = 0
        published_grades: list[Decimal] = []

        for sub in submissions:
            if sub.status == SubmissionStatus.PENDING:
                pending += 1
            elif sub.status == SubmissionStatus.AWAITING_REVIEW:
                if sub.evaluation is not None:
                    ready_to_publish += 1
                else:
                    awaiting_review += 1
            elif sub.status == SubmissionStatus.PUBLISHED:
                published += 1
                if sub.grade is not None:
                    published_grades.append(sub.grade)

        average_grade = None
        if published_grades:
            average_grade = round(
                Decimal(sum(published_grades)) / Decimal(len(published_grades)), 2
            )

        return SubmissionStatsResponse(
            assignment_id=assignment.id,
            total_enrolled=total_enrolled,
            total_submissions=total_submissions,
            pending=pending,
            awaiting_review=awaiting_review,
            ready_to_publish=ready_to_publish,
            published=published,
            average_grade=average_grade,
        )


submission_query_service = SubmissionQueryService()
