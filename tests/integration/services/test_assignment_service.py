import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.assignment import Assignment
from app.models.classroom import Classroom
from app.models.enums import AssignmentType, ReleasePolicyType, SubmissionStatus
from app.models.submission import Submission
from app.schemas.assignment import (
    AssignmentCreateRequest,
    AssignmentUpdateRequest,
    CodeAssignmentConfig,
    LanguageConfig,
    TestCaseConfig,
)
from app.services.assignment_service import assignment_service
from tests.conftest import TenantContext


@pytest.mark.asyncio
async def test_assignment_service_create_and_list_assignment(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    req = AssignmentCreateRequest(
        title="Busca Binária",
        description="Implemente o algoritmo",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config=CodeAssignmentConfig(
            statement="Implemente a solução.",
            languages=[LanguageConfig(name="python3", starter_code="")],
            test_cases=[TestCaseConfig(id=1, input="1\n", expected_output="1\n")],
        ),
    )

    # Act
    created = await assignment_service.create_assignment(classroom, req, db_session)

    # Assert
    assert created.id is not None
    assert created.classroom_id == classroom.id
    assert created.title == "Busca Binária"

    # List
    assignments = await assignment_service.list_assignments_by_classroom(
        classroom.id, db_session
    )
    assert len(assignments) == 1
    assert assignments[0].id == created.id


@pytest.mark.asyncio
async def test_assignment_service_update_assignment(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    assignment = Assignment(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        title="Original",
        description="Original",
        type=AssignmentType.QUESTIONNAIRE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={
            "questions": [
                {
                    "id": 1,
                    "type": "choice",
                    "points": 5.0,
                    "statement": "Qual a complexidade?",
                    "options": [
                        {"id": "a", "text": "O(1)"},
                        {"id": "b", "text": "O(n)"},
                    ],
                    "correct_option_id": "a",
                }
            ]
        },
    )
    db_session.add(assignment)
    await db_session.commit()

    update_req = AssignmentUpdateRequest(
        title="Título Atualizado",
        description="Descrição Atualizada",
        release_policy=ReleasePolicyType.IMMEDIATE,
    )

    # Act
    updated = await assignment_service.update_assignment(
        assignment, update_req, db_session
    )

    # Assert
    assert updated.title == "Título Atualizado"
    assert updated.description == "Descrição Atualizada"
    assert updated.release_policy == ReleasePolicyType.IMMEDIATE


@pytest.mark.asyncio
async def test_assignment_service_delete_when_has_submissions_raises_bad_request(
    tenant: TenantContext, classroom: Classroom, db_session: AsyncSession
):
    # Arrange
    assignment = Assignment(
        id=uuid.uuid4(),
        classroom_id=classroom.id,
        title="Tarefa com submissão",
        description="",
        type=AssignmentType.CODE,
        release_policy=ReleasePolicyType.ON_REVIEW,
        config={},
    )
    db_session.add(assignment)
    await db_session.flush()

    sub = Submission(
        id=uuid.uuid4(),
        assignment_id=assignment.id,
        student_id=tenant.student.user.id,
        content={"code": "print(1)"},
        status=SubmissionStatus.PENDING,
    )
    db_session.add(sub)
    await db_session.commit()

    # Act & Assert
    with pytest.raises(BadRequestException) as exc_info:
        await assignment_service.delete_assignment(assignment, db_session)

    assert "submissões vinculadas" in str(exc_info.value.message)


@pytest.mark.asyncio
async def test_assignment_service_list_student_assignments_computes_all_statuses(
    tenant: TenantContext,
    student_assignments_bundle,
    db_session: AsyncSession,
):
    from app.schemas.assignment import StudentAssignmentStatus

    # Act
    items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=None,
        db=db_session,
    )

    # Assert
    assert len(items) == 5
    by_id = {item.id: item for item in items}

    # 1. Pending (sem submissão)
    p_item = by_id[student_assignments_bundle.pending_assignment.id]
    assert p_item.student_status == StudentAssignmentStatus.PENDING
    assert p_item.has_draft is False
    assert p_item.submission is None
    assert p_item.classroom_name == student_assignments_bundle.classroom.name

    # 2. Overdue (sem submissão, prazo expirado)
    o_item = by_id[student_assignments_bundle.overdue_assignment.id]
    assert o_item.student_status == StudentAssignmentStatus.OVERDUE
    assert o_item.has_draft is False
    assert o_item.submission is None

    # 3. Draft (rascunho dentro do prazo -> pending)
    d_item = by_id[student_assignments_bundle.draft_assignment.id]
    assert d_item.student_status == StudentAssignmentStatus.PENDING
    assert d_item.has_draft is True
    assert d_item.submission is None

    # 4. Submitted (entregue formalmente)
    s_item = by_id[student_assignments_bundle.submitted_assignment.id]
    assert s_item.student_status == StudentAssignmentStatus.SUBMITTED
    assert s_item.has_draft is False
    assert s_item.submission is not None
    assert s_item.submission.status == SubmissionStatus.PENDING

    # 5. Graded (avaliada e publicada com nota)
    g_item = by_id[student_assignments_bundle.graded_assignment.id]
    assert g_item.student_status == StudentAssignmentStatus.GRADED
    assert g_item.has_draft is False
    assert g_item.submission is not None
    assert g_item.submission.status == SubmissionStatus.PUBLISHED
    assert g_item.submission.grade is not None


@pytest.mark.asyncio
async def test_assignment_service_list_student_assignments_with_status_filter(
    tenant: TenantContext,
    student_assignments_bundle,
    db_session: AsyncSession,
):
    from app.schemas.assignment import StudentAssignmentFilterStatus

    # Test pending filter (deve incluir pending sem entrega e com draft)
    pending_items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=StudentAssignmentFilterStatus.PENDING,
        db=db_session,
    )
    assert len(pending_items) == 2

    # Test overdue filter
    overdue_items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=StudentAssignmentFilterStatus.OVERDUE,
        db=db_session,
    )
    assert len(overdue_items) == 1
    assert overdue_items[0].id == student_assignments_bundle.overdue_assignment.id

    # Test submitted filter
    submitted_items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=StudentAssignmentFilterStatus.SUBMITTED,
        db=db_session,
    )
    assert len(submitted_items) == 1
    assert submitted_items[0].id == student_assignments_bundle.submitted_assignment.id

    # Test graded filter
    graded_items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=StudentAssignmentFilterStatus.GRADED,
        db=db_session,
    )
    assert len(graded_items) == 1
    assert graded_items[0].id == student_assignments_bundle.graded_assignment.id

    # Test unsubmitted filter (pending + overdue)
    unsubmitted_items = await assignment_service.list_student_assignments(
        member=tenant.student.member,
        classroom_id=None,
        status_filter=StudentAssignmentFilterStatus.UNSUBMITTED,
        db=db_session,
    )
    assert len(unsubmitted_items) == 3


@pytest.mark.asyncio
async def test_assignment_service_get_student_assignments_summary(
    tenant: TenantContext,
    student_assignments_bundle,
    db_session: AsyncSession,
):
    # Act
    summary = await assignment_service.get_student_assignments_summary(
        member=tenant.student.member,
        classroom_id=None,
        db=db_session,
    )

    # Assert
    assert summary.total == 5
    assert summary.pending == 2
    assert summary.overdue == 1
    assert summary.submitted == 1
    assert summary.graded == 1


@pytest.mark.asyncio
async def test_assignment_service_list_student_assignments_classroom_validation_errors(
    tenant: TenantContext,
    student_assignments_bundle,
    create_tenant,
    create_classroom,
    db_session: AsyncSession,
):
    from app.core.exceptions import ForbiddenException, NotFoundException

    # 1. Sala inexistente -> 404
    non_existent_id = uuid.uuid4()
    with pytest.raises(NotFoundException) as exc_404:
        await assignment_service.list_student_assignments(
            member=tenant.student.member,
            classroom_id=non_existent_id,
            status_filter=None,
            db=db_session,
        )
    assert "não encontrada" in str(exc_404.value.message)

    # 2. Sala de outra organização -> 403
    other_tenant = await create_tenant("Outra Instituição Teste")
    other_org_classroom = await create_classroom(other_tenant)

    with pytest.raises(ForbiddenException) as exc_403_org:
        await assignment_service.list_student_assignments(
            member=tenant.student.member,
            classroom_id=other_org_classroom.id,
            status_filter=None,
            db=db_session,
        )
    assert "outra organização" in str(exc_403_org.value.message)

    # 3. Sala da mesma org mas aluno não matriculado -> 403
    not_enrolled_classroom = await create_classroom(tenant, name="Turma Sem Matrícula")

    with pytest.raises(ForbiddenException) as exc_403_enroll:
        await assignment_service.list_student_assignments(
            member=tenant.student.member,
            classroom_id=not_enrolled_classroom.id,
            status_filter=None,
            db=db_session,
        )
    assert "não é membro" in str(exc_403_enroll.value.message)
