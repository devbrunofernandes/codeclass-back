import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.domain.grading.questionnaire_grader import QuestionnaireGrader
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
    SubmissionEvaluation,
)
from app.schemas.submission import (
    CodeSubmissionContent,
    CodeSubmissionDraftContent,
    QuestionnaireSubmissionContent,
    QuestionnaireSubmissionDraftContent,
    SubmissionCreateRequest,
    SubmissionDraftRequest,
)
from app.services.submission.ai_worker import submission_ai_worker

logger = logging.getLogger(__name__)


class SubmissionLifecycleService:
    """Serviço de gerenciamento do ciclo de vida, máquina de estados e rascunhos de submissões."""

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
        result = QuestionnaireGrader.grade_objective(questions, answers)
        return result.total_points, result.detailed_scores

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
            background_tasks.add_task(
                submission_ai_worker.process_submission_ai_task, sub.id
            )

        return sub

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

    async def save_draft_submission(
        self,
        assignment: Assignment,
        student_id: uuid.UUID,
        request: SubmissionDraftRequest,
        db: AsyncSession,
    ) -> Submission:
        """Salva ou atualiza um rascunho de submissão do aluno sem submissão formal nem disparo de IA."""
        # 1. Valida se o prazo já expirou
        if assignment.deadline and datetime.now(UTC) > assignment.deadline:
            raise BadRequestException("O prazo para esta atividade já expirou.")

        # 2. Valida tipo de conteúdo compatível com a atividade
        content_data = request.content.model_dump()
        if assignment.type == AssignmentType.CODE:
            if not isinstance(request.content, CodeSubmissionDraftContent):
                raise BadRequestException(
                    "Conteúdo inválido: esperado rascunho de código para esta atividade."
                )
            allowed_langs = [
                lang["name"] for lang in assignment.config.get("languages", [])
            ]
            if (
                allowed_langs
                and request.content.language
                and request.content.language not in allowed_langs
            ):
                raise BadRequestException(
                    f"A linguagem '{request.content.language}' não é permitida para esta atividade."
                )
        elif assignment.type == AssignmentType.QUESTIONNAIRE:
            if not isinstance(request.content, QuestionnaireSubmissionDraftContent):
                raise BadRequestException(
                    "Conteúdo inválido: esperado rascunho de respostas de questionário para esta atividade."
                )

        # 3. Consulta submissão existente
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

        # 4. Validação estrita da máquina de estados
        if sub:
            if sub.status == SubmissionStatus.PUBLISHED or sub.evaluation is not None:
                raise BadRequestException(
                    "Esta submissão já foi corrigida e avaliada, não sendo possível alterá-la."
                )
            if sub.status in (
                SubmissionStatus.PENDING,
                SubmissionStatus.AWAITING_REVIEW,
            ):
                raise BadRequestException(
                    "A atividade já foi submetida formalmente. Para editar o rascunho, desfaça a entrega primeiro (unsubmit)."
                )

            # Atualiza rascunho existente
            sub.content = content_data
            sub.status = SubmissionStatus.DRAFT
            sub.submitted_at = func.now()  # type: ignore[assignment]
        else:
            # Cria novo rascunho
            sub = Submission(
                assignment_id=assignment.id,
                student_id=student_id,
                content=content_data,
                status=SubmissionStatus.DRAFT,
            )
            db.add(sub)

        assignment_id = assignment.id
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # Tratamento defensivo de corrida concorrente de criação inicial de rascunho
            stmt = (
                select(Submission)
                .options(selectinload(Submission.evaluation))
                .where(
                    Submission.assignment_id == assignment_id,
                    Submission.student_id == student_id,
                )
            )
            result = await db.execute(stmt)
            sub = result.scalar_one_or_none()
            if not sub:
                raise
            if sub.status == SubmissionStatus.PUBLISHED or sub.evaluation is not None:
                raise BadRequestException(
                    "Esta submissão já foi corrigida e avaliada, não sendo possível alterá-la."
                )
            if sub.status in (
                SubmissionStatus.PENDING,
                SubmissionStatus.AWAITING_REVIEW,
            ):
                raise BadRequestException(
                    "A atividade já foi submetida formalmente. Para editar o rascunho, desfaça a entrega primeiro (unsubmit)."
                )
            sub.content = content_data
            sub.status = SubmissionStatus.DRAFT
            sub.submitted_at = func.now()  # type: ignore[assignment]
            await db.commit()

        await db.refresh(sub)
        return sub

    async def retry_ai_evaluation(
        self,
        submission: Submission,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
    ) -> Submission:
        """Reinicia a análise assíncrona de IA para uma submissão delegando ao worker especializado."""
        return await submission_ai_worker.retry_ai_evaluation(
            submission=submission,
            db=db,
            background_tasks=background_tasks,
        )


submission_lifecycle_service = SubmissionLifecycleService()
