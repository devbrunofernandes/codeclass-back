import logging
import uuid
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.database import async_session_maker
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
)
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)


class SubmissionAiWorker:
    """Worker assíncrono para processamento e reavaliação de submissões com IA."""

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

    async def retry_ai_evaluation(
        self,
        submission: Submission,
        db: AsyncSession,
        background_tasks: BackgroundTasks,
    ) -> Submission:
        """Reinicia a análise assíncrona de IA para uma submissão."""
        stmt = (
            select(Submission)
            .options(
                selectinload(Submission.assignment),
                selectinload(Submission.ai_insight),
                selectinload(Submission.evaluation),
            )
            .where(Submission.id == submission.id)
        )
        res = await db.execute(stmt)
        sub = res.scalar_one_or_none()
        if not sub:
            raise NotFoundException("Submissão não encontrada.")

        if sub.status == SubmissionStatus.PUBLISHED or sub.evaluation is not None:
            raise BadRequestException(
                "Não é possível reprocessar IA para submissões já avaliadas ou com correção publicada."
            )

        if sub.status == SubmissionStatus.DRAFT:
            raise BadRequestException(
                "Não é possível processar IA para uma submissão em estado de rascunho."
            )

        if sub.status == SubmissionStatus.PENDING:
            raise BadRequestException(
                "A submissão já se encontra em processamento de IA."
            )

        # Valida se a atividade requer IA
        assignment = sub.assignment
        questions = assignment.config.get("questions", [])
        is_all_objective = assignment.type == AssignmentType.QUESTIONNAIRE and all(
            q.get("type") == "choice" for q in questions
        )
        if is_all_objective:
            raise BadRequestException(
                "Esta atividade possui correção 100% determinística e não requer análise de IA."
            )

        # Atualiza status e prepara o insight
        if sub.ai_insight:
            sub.ai_insight.status = "in_progress"
            sub.ai_insight.error_message = None
            sub.ai_insight.suggested_grade = None
            sub.ai_insight.max_grade = None
            sub.ai_insight.reasoning = None
            sub.ai_insight.strengths = []
            sub.ai_insight.improvements = []
            sub.ai_insight.item_insights = None
        else:
            sub.ai_insight = SubmissionAiInsight(
                submission_id=sub.id,
                status="in_progress",
            )
            db.add(sub.ai_insight)

        sub.status = SubmissionStatus.PENDING
        await db.commit()

        # Recarrega a submissão com as relações necessárias para evitar lazy loading
        reload_stmt = (
            select(Submission)
            .options(
                selectinload(Submission.assignment).selectinload(Assignment.classroom),
                selectinload(Submission.student),
                selectinload(Submission.ai_insight),
                selectinload(Submission.evaluation),
            )
            .where(Submission.id == sub.id)
        )
        sub = (await db.execute(reload_stmt)).scalar_one()

        background_tasks.add_task(self.process_submission_ai_task, sub.id)
        return sub


submission_ai_worker = SubmissionAiWorker()
process_submission_ai_task = submission_ai_worker.process_submission_ai_task
