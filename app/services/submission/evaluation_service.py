import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
)
from app.models.enums import SubmissionStatus
from app.models.submission import (
    Submission,
    SubmissionEvaluation,
)
from app.schemas.evaluation import SubmissionEvaluationRequest


class SubmissionEvaluationService:
    """Serviço de avaliação docente, pareceres autorais e publicação de notas."""

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


submission_evaluation_service = SubmissionEvaluationService()
