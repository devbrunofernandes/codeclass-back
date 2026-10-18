import pytest

from app.models.submission import SubmissionAiInsight


@pytest.mark.asyncio
async def test_ai_feedback_when_replaced_and_cleared_should_persist_privately(
    async_client, tenant, submission_published, db_session
):
    url = f"/api/v1/submissions/{submission_published.id}"
    for value, details in [
        (True, "Correto"),
        (False, "Nota inconsistente"),
        (None, None),
    ]:
        response = await async_client.put(
            f"{url}/ai-feedback",
            headers=tenant.teacher.auth_headers,
            json={"feedback_positive": value, "feedback_details": details},
        )
        assert response.status_code == 200
        db_session.expire_all()
        insight = await db_session.get(SubmissionAiInsight, response.json()["id"])
        assert insight.feedback_positive is value
        assert insight.feedback_details == details
        detail = await async_client.get(url, headers=tenant.teacher.auth_headers)
        assert detail.json()["ai_insight"]["feedback_positive"] is value
        student = await async_client.get(url, headers=tenant.student.auth_headers)
        assert "ai_insight" not in student.json()


@pytest.mark.asyncio
async def test_ai_feedback_when_reprocessed_should_clear_previous_feedback(
    async_client, tenant, submission_awaiting_review, db_session, mock_ai_service
):
    url = f"/api/v1/submissions/{submission_awaiting_review.id}"
    saved = await async_client.put(
        f"{url}/ai-feedback",
        headers=tenant.teacher.auth_headers,
        json={"feedback_positive": False, "feedback_details": "Revisar análise"},
    )
    assert saved.status_code == 200
    retried = await async_client.post(
        f"{url}/retry-ai", headers=tenant.teacher.auth_headers
    )
    assert retried.status_code == 200
    db_session.expire_all()
    insight = await db_session.get(SubmissionAiInsight, saved.json()["id"])
    assert insight.status == "completed"
    assert insight.feedback_positive is None
    assert insight.feedback_details is None
