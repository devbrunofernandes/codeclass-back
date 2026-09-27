import uuid

import pytest

from app.api.deps.contexts import (
    AssignmentContext,
    ClassroomContext,
    SubmissionContext,
)
from app.api.deps.guards import (
    require_assignment_permission,
    require_classroom_permission,
    require_org_member,
    require_roles,
    require_submission_permission,
)
from app.core.exceptions import ForbiddenException
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


class TestRoleAndOrgGuards:
    def test_require_roles_when_role_allowed_should_succeed(self):
        member = _create_mock_member(OrgRole.ADMIN)
        checker = require_roles(OrgRole.OWNER, OrgRole.ADMIN)
        assert checker(member) == member

    def test_require_roles_when_role_disallowed_should_raise_forbidden(self):
        member = _create_mock_member(OrgRole.STUDENT)
        checker = require_roles(OrgRole.OWNER, OrgRole.ADMIN)
        with pytest.raises(ForbiddenException):
            checker(member)

    @pytest.mark.asyncio
    async def test_require_org_member_when_matching_should_succeed(self):
        org_id = uuid.uuid4()
        member = _create_mock_member(OrgRole.STUDENT, org_id)
        result = await require_org_member(org_id=org_id, member=member)
        assert result == member

    @pytest.mark.asyncio
    async def test_require_org_member_when_mismatched_should_raise_forbidden(self):
        org_id = uuid.uuid4()
        other_org_id = uuid.uuid4()
        member = _create_mock_member(OrgRole.STUDENT, org_id)

        with pytest.raises(ForbiddenException) as exc_info:
            await require_org_member(org_id=other_org_id, member=member)
        assert "outra organização" in str(exc_info.value.message)


class TestClassroomPermissionGuards:
    def test_require_classroom_permission_student_view(self):
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

        checker = require_classroom_permission(can_view=True)
        assert checker(ctx) == ctx

    def test_require_classroom_permission_student_cannot_manage(self):
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

        checker = require_classroom_permission(can_manage=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)

    def test_require_classroom_permission_must_be_teacher(self):
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

        checker = require_classroom_permission(must_be_teacher=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)

    def test_require_classroom_permission_can_manage_attachments(self):
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

        checker = require_classroom_permission(can_manage_attachments=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)


class TestAssignmentPermissionGuards:
    def test_require_assignment_permission_enrolled_student(self):
        org_id = uuid.uuid4()
        student = _create_mock_member(OrgRole.STUDENT, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)
        assignment = _create_mock_assignment(classroom)

        classroom_ctx = ClassroomContext(
            classroom=classroom,
            current_member=student,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=False,
            is_enrolled_student=True,
        )
        ctx = AssignmentContext(assignment=assignment, classroom_context=classroom_ctx)

        checker = require_assignment_permission(must_be_enrolled_student=True)
        assert checker(ctx) == ctx

    def test_require_assignment_permission_non_enrolled_student_fails(self):
        org_id = uuid.uuid4()
        student = _create_mock_member(OrgRole.STUDENT, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)
        assignment = _create_mock_assignment(classroom)

        classroom_ctx = ClassroomContext(
            classroom=classroom,
            current_member=student,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=False,
            is_enrolled_student=False,
        )
        ctx = AssignmentContext(assignment=assignment, classroom_context=classroom_ctx)

        checker = require_assignment_permission(must_be_enrolled_student=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)

    def test_require_assignment_permission_staff_check(self):
        org_id = uuid.uuid4()
        student = _create_mock_member(OrgRole.STUDENT, org_id)
        classroom = _create_mock_classroom(uuid.uuid4(), org_id)
        assignment = _create_mock_assignment(classroom)

        classroom_ctx = ClassroomContext(
            classroom=classroom,
            current_member=student,
            is_owner=False,
            is_admin=False,
            is_teacher_of_class=False,
            is_enrolled_student=True,
        )
        ctx = AssignmentContext(assignment=assignment, classroom_context=classroom_ctx)

        checker = require_assignment_permission(must_be_staff=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)


class TestSubmissionPermissionGuards:
    def test_require_submission_permission_author_view(self):
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
        ctx = SubmissionContext(
            submission=submission,
            assignment_context=assignment_ctx,
            is_submission_author=True,
        )

        checker = require_submission_permission(can_view=True)
        assert checker(ctx) == ctx

    def test_require_submission_permission_author_cannot_evaluate(self):
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
        ctx = SubmissionContext(
            submission=submission,
            assignment_context=assignment_ctx,
            is_submission_author=True,
        )

        checker = require_submission_permission(can_evaluate=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)

    def test_require_submission_permission_author_cannot_view_ai_insights(self):
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
        ctx = SubmissionContext(
            submission=submission,
            assignment_context=assignment_ctx,
            is_submission_author=True,
        )

        checker = require_submission_permission(can_view_ai_insights=True)
        with pytest.raises(ForbiddenException):
            checker(ctx)
