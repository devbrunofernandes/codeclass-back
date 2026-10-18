import pytest
from pydantic import ValidationError

from app.schemas.submission import SubmissionAiFeedbackRequest


@pytest.mark.parametrize("value", [True, False, None])
def test_feedback_when_valid_should_accept_nullable_boolean(value):
    request = SubmissionAiFeedbackRequest(
        feedback_positive=value, feedback_details=None
    )
    assert request.feedback_positive is value


@pytest.mark.parametrize("value", ["positive", "false", 1, 0])
def test_feedback_when_not_boolean_should_reject(value):
    with pytest.raises(ValidationError):
        SubmissionAiFeedbackRequest(feedback_positive=value, feedback_details=None)


def test_feedback_when_missing_fields_should_reject():
    with pytest.raises(ValidationError):
        SubmissionAiFeedbackRequest()
