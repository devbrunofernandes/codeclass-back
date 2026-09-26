import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.database import async_session_maker
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom, ClassroomStudent
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
    SubmissionEvaluation,
)
from app.models.user import User
from app.schemas.evaluation import (
    SubmissionEvaluationRequest,
    SubmissionEvaluationResponse,
)
from app.schemas.submission import (
    CodeSubmissionContent,
    QuestionnaireSubmissionContent,
    SubmissionAiInsightResponse,
    SubmissionAssignmentInfo,
    SubmissionCreateRequest,
    SubmissionDetailStudentResponse,
    SubmissionDetailTeacherResponse,
    SubmissionStatsResponse,
    SubmissionStudentInfo,
)
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)


class SubmissionService:
    def validate_code_content(
        self, language: str, code: str, allowed_languages: list[str]
    ) -> None:
        if not language or not language.strip() or not code or not code.strip():
            raise BadRequestException("Linguagem e código são obrigatórios.")
        if language not in allowed_languages:
            raise BadRequestException(
                f"A linguagem '{language}' não é permitida para esta atividade. Permitidas: {', '.join(allowed_languages)}"
            )

    def grade_objective_questions(
        self,
        questions: list[dict[str, Any]],
        answers: list[dict[str, Any]],
    ) -> tuple[Decimal, dict[str, Any]]:
        answers_by_id = {ans.get("question_id"): ans for ans in answers}
        total_points = Decimal("0.00")
        questions_eval = []

        for q in questions:
            qid = q.get("id")
            max_points = Decimal(str(q.get("points", 0.0)))
            correct_option_id = q.get("correct_option_id")
            ans = answers_by_id.get(qid)
            selected_option_id = ans.get("selected_option_id") if ans else None

            is_correct = bool(
                selected_option_id and selected_option_id == correct_option_id
            )
            awarded = max_points if is_correct else Decimal("0.00")
            total_points += awarded

            questions_eval.append(
                {
                    "question_id": qid,
                    "type": "choice",
                    "awarded_points": float(awarded),
                    "max_points": float(max_points),
                    "is_correct": is_correct,
                }
            )

        return total_points, {"questions_evaluation": questions_eval}

    async def submit_assignment(
        self,
        assignment: Assignment,
        student_id: uuid.UUID,
        request: SubmissionCreateRequest,
        db: AsyncSession,
        background_tasks: BackgroundTasks | None = None,
    ) -> Submission:
        # 1. Valida se o prazo já expirou
        if assignment.deadline and datetime.now(UTC) > assignment.deadline:
            raise BadRequestException("Prazo de entrega expirado.")

        # 2. Verifica submissão existente
        stmt = (
            select(Submission)
            .options(selectinload(Submission.ai_insight))
            .where(
                Submission.assignment_id == assignment.id,
                Submission.student_id == student_id,
            )
        )
        result = await db.execute(stmt)
        existing_sub = result.scalar_one_or_none()

        if existing_sub and existing_sub.status != SubmissionStatus.DRAFT:
            raise ConflictException(
                "Aluno já possui submissão ativa ou avaliada para esta atividade."
            )

        content_data = request.content.model_dump()
        target_status = SubmissionStatus.PENDING
        calculated_grade: Decimal | None = None
        evaluation_record: SubmissionEvaluation | None = None
        needs_ai_task = False

        # 3. Validação e processamento de acordo com o tipo da tarefa
        if assignment.type == AssignmentType.CODE:
            if not isinstance(request.content, CodeSubmissionContent):
                raise BadRequestException(
                    "Conteúdo inválido: esperado envio de código para esta atividade."
                )
            allowed_langs = [
                lang["name"] for lang in assignment.config.get("languages", [])
            ]
            self.validate_code_content(
                request.content.language, request.content.code, allowed_langs
            )

            # Idempotência no reenvio de draft com código idêntico
            if (
                existing_sub
                and existing_sub.ai_insight
                and existing_sub.ai_insight.status == "completed"
                and existing_sub.content == content_data
            ):
                target_status = SubmissionStatus.AWAITING_REVIEW
                needs_ai_task = False
            else:
                target_status = SubmissionStatus.PENDING
                needs_ai_task = True

        elif assignment.type == AssignmentType.QUESTIONNAIRE:
            if not isinstance(request.content, QuestionnaireSubmissionContent):
                raise BadRequestException(
                    "Conteúdo inválido: esperado respostas de questionário para esta atividade."
                )

            questions = assignment.config.get("questions", [])
            is_all_objective = all(q.get("type") == "choice" for q in questions)

            if is_all_objective:
                # Auto-correção determinística de questionário 100% objetivo (zero IA)
                answers_data: list[dict[str, Any]] = [
                    a.model_dump() for a in request.content.answers
                ]
                grade, detailed = self.grade_objective_questions(
                    questions, answers_data
                )

                if assignment.release_policy == ReleasePolicyType.IMMEDIATE:
                    target_status = SubmissionStatus.PUBLISHED
                    calculated_grade = grade
                else:
                    target_status = SubmissionStatus.AWAITING_REVIEW
                    calculated_grade = None  # Retido para o estudante

                evaluation_record = SubmissionEvaluation(
                    grade=grade,
                    general_feedback="Correção automática",
                    detailed_scores=detailed,
                )
                needs_ai_task = False
            else:
                # Questionário misto ou dissertativo (requer IA)
                if (
                    existing_sub
                    and existing_sub.ai_insight
                    and existing_sub.ai_insight.status == "completed"
                    and existing_sub.content == content_data
                ):
                    target_status = SubmissionStatus.AWAITING_REVIEW
                    needs_ai_task = False
                else:
                    target_status = SubmissionStatus.PENDING
                    needs_ai_task = True
        else:
            raise BadRequestException(
                f"Tipo de atividade não suportado: {assignment.type}"
            )

        # 4. Criação ou atualização do registro
        if existing_sub:
            sub = existing_sub
            sub.content = content_data
            sub.status = target_status
            sub.grade = calculated_grade
            sub.submitted_at = func.now()  # type: ignore[assignment]
        else:
            sub = Submission(
                assignment_id=assignment.id,
                student_id=student_id,
                content=content_data,
                status=target_status,
                grade=calculated_grade,
            )
            db.add(sub)

        # 5. Configuração do registro de ai_insight se necessário
        if needs_ai_task:
            if existing_sub and existing_sub.ai_insight:
                existing_sub.ai_insight.status = "in_progress"
                existing_sub.ai_insight.error_message = None
                existing_sub.ai_insight.suggested_grade = None
                existing_sub.ai_insight.max_grade = None
                existing_sub.ai_insight.reasoning = None
                existing_sub.ai_insight.strengths = []
                existing_sub.ai_insight.improvements = []
                existing_sub.ai_insight.item_insights = None
            elif existing_sub:
                existing_sub.ai_insight = SubmissionAiInsight(
                    submission_id=existing_sub.id,
                    status="in_progress",
                )
            else:
                sub.ai_insight = SubmissionAiInsight(
                    status="in_progress",
                )

        try:
            await db.flush()

            if evaluation_record:
                eval_stmt = select(SubmissionEvaluation).where(
                    SubmissionEvaluation.submission_id == sub.id
                )
                existing_eval = (await db.execute(eval_stmt)).scalar_one_or_none()
                if existing_eval:
                    existing_eval.grade = evaluation_record.grade
                    existing_eval.general_feedback = evaluation_record.general_feedback
                    existing_eval.detailed_scores = evaluation_record.detailed_scores
                else:
                    evaluation_record.submission_id = sub.id
                    db.add(evaluation_record)

            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise ConflictException(
                "Aluno já possui submissão ativa ou avaliada para esta atividade."
            )

        await db.refresh(sub)

        # 6. Agenda worker de IA assíncrona se necessário
        if needs_ai_task and background_tasks:
            background_tasks.add_task(self.process_submission_ai_task, sub.id)

        return sub

    async def process_submission_ai_task(self, submission_id: uuid.UUID) -> None:
        """Executa a inferência pedagógica assíncrona com IA em sessão isolada de banco."""
        async with async_session_maker() as session:
            try:
                stmt = (
                    select(Submission)
                    .options(
                        joinedload(Submission.assignment),
                        joinedload(Submission.ai_insight),
                    )
                    .where(Submission.id == submission_id)
                )
                result = await session.execute(stmt)
                sub = result.scalar_one_or_none()
                if not sub or not sub.assignment:
                    logger.warning(
                        "Submissão %s não encontrada para processamento de IA.",
                        submission_id,
                    )
                    return

                if sub.status != SubmissionStatus.PENDING:
                    logger.info(
                        "Submissão %s não está no status PENDING (%s), pulando IA.",
                        submission_id,
                        sub.status,
                    )
                    return

                # Chama AiService para gerar os pareceres e notas
                insight = await ai_service.evaluate_submission(
                    assignment=sub.assignment,
                    submission_content=sub.content,
                )

                if not sub.ai_insight:
                    sub.ai_insight = SubmissionAiInsight(submission_id=sub.id)
                    session.add(sub.ai_insight)

                sub.ai_insight.status = "completed"
                sub.ai_insight.suggested_grade = Decimal(str(insight.suggested_grade))
                sub.ai_insight.max_grade = Decimal(str(insight.max_grade))
                sub.ai_insight.reasoning = insight.reasoning
                sub.ai_insight.strengths = insight.strengths
                sub.ai_insight.improvements = insight.improvements
                sub.ai_insight.item_insights = (
                    [item.model_dump() for item in insight.item_insights]
                    if insight.item_insights
                    else None
                )
                sub.ai_insight.error_message = None

                # Transita status para AWAITING_REVIEW (pronto para o professor)
                sub.status = SubmissionStatus.AWAITING_REVIEW
                await session.commit()
                logger.info(
                    "Processamento de IA concluído para submissão %s.", submission_id
                )

            except Exception as exc:
                logger.exception(
                    "Falha ao processar submissão %s com IA", submission_id
                )
                await session.rollback()

                # Resiliência: marca status='failed' e transita submissão para AWAITING_REVIEW (HLD 9.2)
                try:
                    stmt = (
                        select(Submission)
                        .options(joinedload(Submission.ai_insight))
                        .where(Submission.id == submission_id)
                    )
                    result = await session.execute(stmt)
                    sub = result.scalar_one_or_none()
                    if sub:
                        if not sub.ai_insight:
                            sub.ai_insight = SubmissionAiInsight(submission_id=sub.id)
                            session.add(sub.ai_insight)
                        sub.ai_insight.status = "failed"
                        sub.ai_insight.error_message = str(exc)
                        sub.status = SubmissionStatus.AWAITING_REVIEW
                        await session.commit()
                except Exception as inner_exc:  # noqa: BLE001
                    logger.error(
                        "Falha ao registrar status de fallback para submissão %s: %s",
                        submission_id,
                        inner_exc,
                    )

    async def unsubmit_assignment(
        self,
        assignment: Assignment,
        student_id: uuid.UUID,
        db: AsyncSession,
    ) -> Submission:
        stmt = (
            select(Submission)
            .options(selectinload(Submission.evaluation))
            .where(
                Submission.assignment_id == assignment.id,
                Submission.student_id == student_id,
            )
        )
        result = await db.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            raise NotFoundException("Nenhuma entrega encontrada para esta atividade.")

        if assignment.deadline and datetime.now(UTC) > assignment.deadline:
            raise BadRequestException(
                "Não é possível desfazer a entrega após o encerramento do prazo."
            )

        if sub.status == SubmissionStatus.DRAFT:
            raise BadRequestException("A entrega já se encontra em rascunho.")

        if sub.status == SubmissionStatus.PUBLISHED or sub.evaluation is not None:
            raise BadRequestException(
                "Não é possível desfazer uma entrega já avaliada ou que possui correção docente."
            )

        sub.status = SubmissionStatus.DRAFT
        await db.commit()
        await db.refresh(sub)
        return sub

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

    async def evaluate_submission(
        self,
        submission: Submission,
        request: SubmissionEvaluationRequest,
        db: AsyncSession,
    ) -> SubmissionEvaluation:
        """Registra ou atualiza a avaliação docente formal de uma submissão."""
        if submission.status == SubmissionStatus.DRAFT:
            raise BadRequestException("Não é possível avaliar uma entrega em rascunho.")
        if submission.status == SubmissionStatus.PENDING:
            raise BadRequestException(
                "A submissão ainda está em processamento inicial. Aguarde a conclusão da análise para avaliá-la."
            )

        eval_stmt = select(SubmissionEvaluation).where(
            SubmissionEvaluation.submission_id == submission.id
        )
        evaluation = (await db.execute(eval_stmt)).scalar_one_or_none()

        if evaluation:
            evaluation.grade = request.grade
            evaluation.general_feedback = request.general_feedback
            evaluation.detailed_scores = request.detailed_scores
        else:
            evaluation = SubmissionEvaluation(
                submission_id=submission.id,
                grade=request.grade,
                general_feedback=request.general_feedback,
                detailed_scores=request.detailed_scores,
            )
            db.add(evaluation)

        if request.publish:
            submission.status = SubmissionStatus.PUBLISHED
            submission.grade = request.grade
        else:
            submission.status = SubmissionStatus.AWAITING_REVIEW
            submission.grade = None

        await db.commit()
        await db.refresh(evaluation)
        await db.refresh(submission)
        return evaluation

    async def get_submission_evaluation(
        self,
        submission: Submission,
        is_teacher_or_admin: bool,
        is_author: bool,
        db: AsyncSession,
    ) -> SubmissionEvaluation:
        """Consulta a avaliação formal docente de uma submissão com controle de retenção."""
        if (
            is_author
            and not is_teacher_or_admin
            and submission.status != SubmissionStatus.PUBLISHED
        ):
            raise ForbiddenException(
                "Acesso negado: a avaliação desta atividade ainda não foi publicada."
            )

        eval_stmt = select(SubmissionEvaluation).where(
            SubmissionEvaluation.submission_id == submission.id
        )
        evaluation = (await db.execute(eval_stmt)).scalar_one_or_none()

        if not evaluation:
            raise NotFoundException("Avaliação não encontrada para esta submissão.")

        return evaluation

    async def publish_assignment_evaluations(
        self,
        assignment_id: uuid.UUID,
        db: AsyncSession,
        submission_ids: list[uuid.UUID] | None = None,
    ) -> int:
        """Publica em lote submissões de uma tarefa que possuem avaliação registrada e estão com status awaiting_review."""
        stmt = (
            select(Submission)
            .options(selectinload(Submission.evaluation))
            .where(
                Submission.assignment_id == assignment_id,
                Submission.status == SubmissionStatus.AWAITING_REVIEW,
            )
        )
        if submission_ids is not None:
            stmt = stmt.where(Submission.id.in_(submission_ids))

        result = await db.execute(stmt)
        submissions = result.scalars().all()

        published_count = 0
        for sub in submissions:
            if sub.evaluation is not None:
                sub.status = SubmissionStatus.PUBLISHED
                sub.grade = sub.evaluation.grade
                published_count += 1

        if published_count > 0:
            await db.commit()

        return published_count

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


submission_service = SubmissionService()
