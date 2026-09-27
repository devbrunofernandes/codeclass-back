from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.grading.questionnaire_grader import QuestionEvaluationItem

__all__ = [
    "BatchEvaluationReleaseRequest",
    "BatchEvaluationReleaseResponse",
    "QuestionEvaluationItem",
    "SubmissionEvaluationRequest",
    "SubmissionEvaluationResponse",
]


class SubmissionEvaluationRequest(BaseModel):
    grade: Decimal = Field(ge=Decimal("0.00"), le=Decimal("100.00"))
    general_feedback: str | None = None
    detailed_scores: dict[str, Any] | None = None
    publish: bool = True

    model_config = ConfigDict(str_strip_whitespace=True)


class SubmissionEvaluationResponse(BaseModel):
    id: UUID
    submission_id: UUID
    grade: Decimal
    general_feedback: str | None = None
    detailed_scores: dict[str, Any] | None = None
    evaluated_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BatchEvaluationReleaseRequest(BaseModel):
    submission_ids: list[UUID] | None = None


class BatchEvaluationReleaseResponse(BaseModel):
    assignment_id: UUID
    published_count: int = Field(ge=0)
    message: str
