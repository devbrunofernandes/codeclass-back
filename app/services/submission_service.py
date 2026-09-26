import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import Submission, SubmissionEvaluation
from app.schemas.submission import (
    CodeSubmissionContent,
    QuestionnaireSubmissionContent,
    SubmissionCreateRequest,
)


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
    ) -> Submission:
        # 1. Valida se o prazo já expirou
        if assignment.deadline and datetime.now(UTC) > assignment.deadline:
            raise BadRequestException("Prazo de entrega expirado.")

        # 2. Verifica submissão existente
        stmt = select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student_id,
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
            target_status = SubmissionStatus.PENDING

        elif assignment.type == AssignmentType.QUESTIONNAIRE:
            if not isinstance(request.content, QuestionnaireSubmissionContent):
                raise BadRequestException(
                    "Conteúdo inválido: esperado respostas de questionário para esta atividade."
                )

            questions = assignment.config.get("questions", [])
            is_all_objective = all(q.get("type") == "choice" for q in questions)

            if is_all_objective:
                # Auto-correção determinística de questionário 100% objetivo
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
            else:
                target_status = SubmissionStatus.PENDING
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
        return sub

    async def unsubmit_assignment(
        self,
        assignment: Assignment,
        student_id: uuid.UUID,
        db: AsyncSession,
    ) -> Submission:
        stmt = select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student_id,
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

        if sub.status == SubmissionStatus.PUBLISHED:
            raise BadRequestException(
                "Não é possível desfazer uma entrega já avaliada/publicada."
            )

        sub.status = SubmissionStatus.DRAFT
        await db.commit()
        await db.refresh(sub)
        return sub

    async def get_my_submission(
        self,
        assignment: Assignment,
        student_id: uuid.UUID,
        db: AsyncSession,
    ) -> Submission:
        stmt = select(Submission).where(
            Submission.assignment_id == assignment.id,
            Submission.student_id == student_id,
        )
        result = await db.execute(stmt)
        sub = result.scalar_one_or_none()

        if not sub:
            raise NotFoundException("Nenhuma entrega encontrada para esta atividade.")

        return sub


submission_service = SubmissionService()
