import logging
import uuid
from copy import deepcopy
from decimal import Decimal

from fastapi import BackgroundTasks
from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import async_session_maker
from app.core.exceptions import (
    BadRequestException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionAiInsight,
)
from app.schemas.submission import AiInsightResult
from app.services.ai_service import ai_service

logger = logging.getLogger(__name__)


class SubmissionAiWorker:
    """Worker assíncrono para processamento e reavaliação de submissões com IA."""

    @staticmethod
    def _attempt_scope(
        submission_id: uuid.UUID,
        attempt_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ColumnElement[bool]:
        return and_(
            Submission.id == submission_id,
            Submission.processing_attempt_id == attempt_id,
            Submission.status == SubmissionStatus.PENDING,
            Submission.assignment_id.in_(
                select(Assignment.id)
                .join(Classroom, Assignment.classroom_id == Classroom.id)
                .where(Classroom.organization_id == organization_id)
            ),
        )

    async def _complete_attempt(
        self,
        submission_id: uuid.UUID,
        attempt_id: uuid.UUID,
        organization_id: uuid.UUID,
        insight: AiInsightResult | None,
        error_message: str | None = None,
    ) -> None:
        # The conditional UPDATE claims completion and holds a short row lock.
        # Insights and state commit together; duplicate/obsolete jobs affect zero rows.
        async with async_session_maker() as session, session.begin():
            claimed = await session.scalar(
                update(Submission)
                .where(self._attempt_scope(submission_id, attempt_id, organization_id))
                .values(status=SubmissionStatus.AWAITING_REVIEW)
                .returning(Submission.id)
            )
            if claimed is None:
                return
            values = {
                "submission_id": submission_id,
                "status": "completed" if insight else "failed",
                "suggested_grade": Decimal(str(insight.suggested_grade))
                if insight
                else None,
                "max_grade": Decimal(str(insight.max_grade)) if insight else None,
                "reasoning": insight.reasoning if insight else None,
                "strengths": insight.strengths if insight else [],
                "improvements": insight.improvements if insight else [],
                "item_insights": (
                    [item.model_dump() for item in insight.item_insights]
                    if insight and insight.item_insights
                    else None
                ),
                "error_message": error_message,
            }
            statement = insert(SubmissionAiInsight).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[SubmissionAiInsight.submission_id],
                    set_={**values, "updated_at": func.now()},
                )
            )

    async def process_submission_ai_task(
        self,
        submission_id: uuid.UUID,
        attempt_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:
        """Captura a tentativa em sessão própria, sem transação durante a inferência."""
        try:
            async with async_session_maker() as session:
                sub = (
                    await session.execute(
                        select(Submission)
                        .options(joinedload(Submission.assignment))
                        .where(
                            self._attempt_scope(
                                submission_id, attempt_id, organization_id
                            )
                        )
                    )
                ).scalar_one_or_none()
                if sub is None or sub.status != SubmissionStatus.PENDING:
                    return
                assignment = sub.assignment
                content = deepcopy(sub.content)
                session.expunge(assignment)

            insight = await ai_service.evaluate_submission(
                assignment=assignment,
                submission_content=content,
            )
            await self._complete_attempt(
                submission_id,
                attempt_id,
                organization_id,
                insight,
            )
        except Exception as exc:
            logger.exception("Falha ao processar submissão %s com IA", submission_id)
            try:
                await self._complete_attempt(
                    submission_id,
                    attempt_id,
                    organization_id,
                    None,
                    str(exc),
                )
            except Exception:
                logger.exception(
                    "Falha ao registrar fallback para submissão %s",
                    submission_id,
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
            .with_for_update(of=Submission)
            .execution_options(populate_existing=True)
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
            sub.ai_insight.feedback_positive = None
            sub.ai_insight.feedback_details = None
        else:
            sub.ai_insight = SubmissionAiInsight(
                submission_id=sub.id,
                status="in_progress",
            )
            db.add(sub.ai_insight)

        attempt_id = uuid.uuid4()
        organization_id = await db.scalar(
            select(Classroom.organization_id).where(
                Classroom.id == assignment.classroom_id
            )
        )
        if organization_id is None:
            raise NotFoundException("Organização da atividade não encontrada.")
        sub.processing_attempt_id = attempt_id
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

        background_tasks.add_task(
            self.process_submission_ai_task, sub.id, attempt_id, organization_id
        )
        return sub


submission_ai_worker = SubmissionAiWorker()
process_submission_ai_task = submission_ai_worker.process_submission_ai_task
