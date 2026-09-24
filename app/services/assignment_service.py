from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, ReleasePolicyType
from app.models.submission import Submission
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentStudentResponse,
    AssignmentTeacherResponse,
    AssignmentUpdateRequest,
    CodeAssignmentConfig,
    QuestionnaireAssignmentConfig,
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


assignment_service = AssignmentService()
