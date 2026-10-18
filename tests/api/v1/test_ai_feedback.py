import uuid

import pytest

from app.models.enums import SubmissionStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False, None])
async def test_save_ai_feedback_when_teacher_should_return_200(
    async_client, tenant, submission_awaiting_review, value
):
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": value, "feedback_details": "Justificativa"},
    )
    assert response.status_code == 200
    assert response.json()["feedback_positive"] is value
    assert response.json()["feedback_details"] == "Justificativa"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["student", "admin", "owner", "other_teacher"])
async def test_save_ai_feedback_when_not_teacher_should_return_403(
    async_client, tenant, submission_awaiting_review, role
):
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=getattr(tenant, role).auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_save_ai_feedback_when_unauthenticated_should_return_401(
    async_client, submission_awaiting_review
):
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_save_ai_feedback_when_missing_should_return_404(async_client, tenant):
    response = await async_client.put(
        f"/api/v1/submissions/{uuid.uuid4()}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"feedback_positive": "positive", "feedback_details": None}]
)
async def test_save_ai_feedback_when_invalid_should_return_422(
    async_client, tenant, submission_awaiting_review, payload
):
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json=payload,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_save_ai_feedback_when_other_tenant_should_return_403(
    async_client, create_tenant, submission_awaiting_review
):
    other = await create_tenant("Outra instituição feedback")
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=other.teacher.auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "draft"])
async def test_save_ai_feedback_when_unavailable_should_return_400(
    async_client, tenant, submission_awaiting_review, db_session, status
):
    submission_awaiting_review.status = SubmissionStatus(status)
    await db_session.commit()
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_save_ai_feedback_when_insight_missing_should_return_404(
    async_client, tenant, submission_awaiting_review, db_session
):
    await db_session.delete(submission_awaiting_review.ai_insight)
    await db_session.commit()
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_save_ai_feedback_when_member_inactive_should_return_403(
    async_client, tenant, submission_awaiting_review, db_session
):
    tenant.teacher.member.is_active = False
    await db_session.commit()
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_save_ai_feedback_when_user_revoked_should_return_401(
    async_client, tenant, submission_awaiting_review, db_session
):
    headers = tenant.other_teacher.auth_headers
    await db_session.delete(tenant.other_teacher.user)
    await db_session.commit()
    response = await async_client.put(
        f"/api/v1/submissions/{submission_awaiting_review.id}/ai-feedback",
        headers=headers,
        json={"feedback_positive": True, "feedback_details": None},
    )
    assert response.status_code == 401
