from dataclasses import dataclass

from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.organization import OrganizationMember
from app.models.submission import Submission


@dataclass
class ClassroomContext:
    """Contexto de segurança e acesso no escopo de sala de aula."""

    classroom: Classroom
    current_member: OrganizationMember
    is_owner: bool
    is_admin: bool
    is_teacher_of_class: bool
    is_enrolled_student: bool

    @property
    def can_manage_classroom(self) -> bool:
        return self.is_owner or self.is_admin or self.is_teacher_of_class

    @property
    def can_manage_attachments(self) -> bool:
        return self.is_owner or self.is_teacher_of_class

    @property
    def can_view(self) -> bool:
        return self.can_manage_classroom or self.is_enrolled_student


@dataclass
class AssignmentContext:
    """Contexto de segurança e acesso no escopo de atividade pedagógica."""

    assignment: Assignment
    classroom_context: ClassroomContext

    @property
    def classroom(self) -> Classroom:
        return self.classroom_context.classroom

    @property
    def current_member(self) -> OrganizationMember:
        return self.classroom_context.current_member

    @property
    def is_owner(self) -> bool:
        return self.classroom_context.is_owner

    @property
    def is_admin(self) -> bool:
        return self.classroom_context.is_admin

    @property
    def is_teacher_of_class(self) -> bool:
        return self.classroom_context.is_teacher_of_class

    @property
    def is_enrolled_student(self) -> bool:
        return self.classroom_context.is_enrolled_student

    @property
    def can_manage_classroom(self) -> bool:
        return self.classroom_context.can_manage_classroom

    @property
    def can_view(self) -> bool:
        return self.classroom_context.can_view

    @property
    def can_manage(self) -> bool:
        return self.classroom_context.is_teacher_of_class


@dataclass
class SubmissionContext:
    """Contexto de segurança e acesso no escopo de submissão de atividade."""

    submission: Submission
    assignment_context: AssignmentContext
    is_submission_author: bool

    @property
    def assignment(self) -> Assignment:
        return self.assignment_context.assignment

    @property
    def classroom_context(self) -> ClassroomContext:
        return self.assignment_context.classroom_context

    @property
    def classroom(self) -> Classroom:
        return self.assignment_context.classroom

    @property
    def current_member(self) -> OrganizationMember:
        return self.assignment_context.current_member

    @property
    def is_owner(self) -> bool:
        return self.assignment_context.is_owner

    @property
    def is_admin(self) -> bool:
        return self.assignment_context.is_admin

    @property
    def is_teacher_of_class(self) -> bool:
        return self.assignment_context.is_teacher_of_class

    @property
    def is_enrolled_student(self) -> bool:
        return self.assignment_context.is_enrolled_student

    @property
    def can_manage_classroom(self) -> bool:
        return self.assignment_context.can_manage_classroom

    @property
    def can_view(self) -> bool:
        return (
            self.assignment_context.is_owner
            or self.assignment_context.is_admin
            or self.assignment_context.is_teacher_of_class
            or self.is_submission_author
        )

    @property
    def can_evaluate(self) -> bool:
        return self.assignment_context.is_teacher_of_class

    @property
    def can_view_ai_insights(self) -> bool:
        return (
            self.assignment_context.is_owner
            or self.assignment_context.is_admin
            or self.assignment_context.is_teacher_of_class
        )
