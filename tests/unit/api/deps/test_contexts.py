import uuid

from app.api.deps.contexts import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
)
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.submission import Submission


def _create_mock_member(
    role: OrgRole, org_id: uuid.UUID | None = None
) -> OrganizationMember:
    member = OrganizationMember()
    member.id = uuid.uuid4()
    member.user_id = uuid.uuid4()
    member.organization_id = org_id or uuid.uuid4()
    member.role = role
    member.is_active = True
    return member


def _create_mock_classroom(teacher_id: uuid.UUID, org_id: uuid.UUID) -> Classroom:
    classroom = Classroom()
    classroom.id = uuid.uuid4()
    classroom.teacher_id = teacher_id
    classroom.organization_id = org_id
    classroom.name = "Turma Teste"
    return classroom


def _create_mock_assignment(classroom: Classroom) -> Assignment:
    assignment = Assignment()
    assignment.id = uuid.uuid4()
    assignment.classroom_id = classroom.id
    assignment.classroom = classroom
    assignment.title = "Tarefa Teste"
    return assignment


def _create_mock_submission(
    assignment: Assignment, student_id: uuid.UUID
) -> Submission:
    sub = Submission()
    sub.id = uuid.uuid4()
    sub.assignment_id = assignment.id
    sub.assignment = assignment
    sub.student_id = student_id
    return sub


class TestClassroomContext:
    def test_teacher_properties(self):
        org_id = uuid.uuid4()
        teacher = _create_mock_member(OrgRole.TEACHER, org_id)
        classroom = _create_mock_classroom(teacher.user_id, org_id)

        ctx = ClassroomContext(
            classroom=classroom,
            current_member=teacher,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=True,
            is_enrolled_student=False,
        )
        assert ctx.can_manage_classroom is True
        assert ctx.can_manage_attachments is True
        assert ctx.can_view is True

    def test_owner_and_admin_properties(self):
        org_id = uuid.uuid4()
        admin = _create_mock_member(OrgRole.ADMIN, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)

        ctx = ClassroomContext(
            classroom=classroom,
            current_member=admin,
            is_owner=False,
            is_admin=True,
            is_teacher_of_class=False,
            is_enrolled_student=False,
        )
        assert ctx.can_manage_classroom is True
        assert ctx.can_manage_attachments is False
        assert ctx.can_view is True

    def test_student_properties(self):
        org_id = uuid.uuid4()
        student = _create_mock_member(OrgRole.STUDENT, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)

        ctx = ClassroomContext(
            classroom=classroom,
            current_member=student,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=False,
            is_enrolled_student=True,
        )
        assert ctx.can_manage_classroom is False
        assert ctx.can_manage_attachments is False
        assert ctx.can_view is True


class TestAssignmentContext:
    def test_composes_classroom_context_correctly(self):
        org_id = uuid.uuid4()
        teacher = _create_mock_member(OrgRole.TEACHER, org_id)
        classroom = _create_mock_classroom(teacher.user_id, org_id)
        assignment = _create_mock_assignment(classroom)

        classroom_ctx = ClassroomContext(
            classroom=classroom,
            current_member=teacher,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=True,
            is_enrolled_student=False,
        )
        assignment_ctx = AssignmentContext(
            assignment=assignment,
            classroom_context=classroom_ctx,
        )

        assert assignment_ctx.classroom == classroom
        assert assignment_ctx.current_member == teacher
        assert assignment_ctx.is_teacher_of_class is True
        assert assignment_ctx.can_manage is True
        assert assignment_ctx.can_view is True
        assert assignment_ctx.classroom_context == classroom_ctx


class TestSubmissionContext:
    def test_composes_assignment_context_correctly(self):
        org_id = uuid.uuid4()
        student = _create_mock_member(OrgRole.STUDENT, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)
        assignment = _create_mock_assignment(classroom)
        submission = _create_mock_submission(assignment, student.user_id)

        classroom_ctx = ClassroomContext(
            classroom=classroom,
            current_member=student,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=False,
            is_enrolled_student=True,
        )
        assignment_ctx = AssignmentContext(
            assignment=assignment,
            classroom_context=classroom_ctx,
        )
        submission_ctx = SubmissionContext(
            submission=submission,
            assignment_context=assignment_ctx,
            is_submission_author=True,
        )

        assert submission_ctx.submission == submission
        assert submission_ctx.assignment == assignment
        assert submission_ctx.classroom == classroom
        assert submission_ctx.current_member == student
        assert submission_ctx.is_submission_author is True
        assert submission_ctx.can_view is True
        assert submission_ctx.can_evaluate is False
        assert submission_ctx.can_view_ai_insights is False
