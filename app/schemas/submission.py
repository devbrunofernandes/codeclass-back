from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import AssignmentType, SubmissionStatus
from app.schemas.evaluation import SubmissionEvaluationResponse


class CodeSubmissionContent(BaseModel):
    language: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1)


class ChoiceAnswerContent(BaseModel):
    question_id: int = Field(ge=1)
    selected_option_id: str = Field(min_length=1, max_length=50)


class OpenAnswerContent(BaseModel):
    question_id: int = Field(ge=1)
    text_answer: str = Field(min_length=1)


AnswerItemContent = Annotated[
    ChoiceAnswerContent | OpenAnswerContent,
    Field(union_mode="left_to_right"),
]


class QuestionnaireSubmissionContent(BaseModel):
    answers: list[AnswerItemContent] = Field(min_length=1)

    @field_validator("answers")
    @classmethod
    def validate_unique_question_ids(
        cls, answers: list[ChoiceAnswerContent | OpenAnswerContent]
    ) -> list[ChoiceAnswerContent | OpenAnswerContent]:
        seen_ids = set()
        for ans in answers:
            if ans.question_id in seen_ids:
                raise ValueError(
                    f"A questão com ID {ans.question_id} foi respondida mais de uma vez."
                )
            seen_ids.add(ans.question_id)
        return answers


class SubmissionCreateRequest(BaseModel):
    content: CodeSubmissionContent | QuestionnaireSubmissionContent


class CodeSubmissionDraftContent(BaseModel):
    language: str = Field(default="python3", max_length=50)
    code: str = Field(default="")


class ChoiceAnswerDraftContent(BaseModel):
    question_id: int = Field(ge=1)
    selected_option_id: str | None = None


class OpenAnswerDraftContent(BaseModel):
    question_id: int = Field(ge=1)
    text_answer: str | None = None


AnswerItemDraftContent = Annotated[
    ChoiceAnswerDraftContent | OpenAnswerDraftContent,
    Field(union_mode="left_to_right"),
]


class QuestionnaireSubmissionDraftContent(BaseModel):
    answers: list[AnswerItemDraftContent] = Field(default_factory=list)

    @field_validator("answers")
    @classmethod
    def validate_unique_question_ids(
        cls, answers: list[ChoiceAnswerDraftContent | OpenAnswerDraftContent]
    ) -> list[ChoiceAnswerDraftContent | OpenAnswerDraftContent]:
        seen_ids = set()
        for ans in answers:
            if ans.question_id in seen_ids:
                raise ValueError(
                    f"A questão com ID {ans.question_id} foi respondida mais de uma vez."
                )
            seen_ids.add(ans.question_id)
        return answers


class SubmissionDraftRequest(BaseModel):
    content: CodeSubmissionDraftContent | QuestionnaireSubmissionDraftContent


class SubmissionStudentResponse(BaseModel):
    id: UUID
    assignment_id: UUID
    student_id: UUID
    content: dict[str, Any]
    grade: Decimal | None = None
    status: SubmissionStatus
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AiItemInsightSchema(BaseModel):
    question_id: int = Field(ge=1)
    suggested_grade: float = Field(ge=0.0)
    max_grade: float = Field(ge=0.0)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reasoning: str


class AiInsightResult(BaseModel):
    suggested_grade: float = Field(ge=0.0)
    max_grade: float = Field(ge=0.0)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    reasoning: str
    item_insights: list[AiItemInsightSchema] | None = None


class SubmissionAiInsightResponse(BaseModel):
    id: UUID
    submission_id: UUID
    status: str
    suggested_grade: Decimal | None = None
    max_grade: Decimal | None = None
    reasoning: str | None = None
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    item_insights: list[dict[str, Any]] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionAssignmentInfo(BaseModel):
    id: UUID
    title: str
    type: AssignmentType
    classroom_id: UUID

    model_config = ConfigDict(from_attributes=True)


class SubmissionStudentInfo(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr

    model_config = ConfigDict(from_attributes=True)


class SubmissionSummaryStudentResponse(BaseModel):
    id: UUID
    assignment: SubmissionAssignmentInfo
    student: SubmissionStudentInfo
    grade: Decimal | None = None
    status: SubmissionStatus
    submitted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubmissionSummaryTeacherResponse(BaseModel):
    id: UUID
    assignment: SubmissionAssignmentInfo
    student: SubmissionStudentInfo
    grade: Decimal | None = None
    status: SubmissionStatus
    submitted_at: datetime
    ai_insight_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


# Alias para retrocompatibilidade
SubmissionSummaryResponse = SubmissionSummaryTeacherResponse


class SubmissionDetailStudentResponse(BaseModel):
    id: UUID
    assignment: SubmissionAssignmentInfo
    student: SubmissionStudentInfo
    content: dict[str, Any]
    grade: Decimal | None = None
    status: SubmissionStatus
    submitted_at: datetime
    evaluation: SubmissionEvaluationResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class SubmissionDetailTeacherResponse(BaseModel):
    id: UUID
    assignment: SubmissionAssignmentInfo
    student: SubmissionStudentInfo
    content: dict[str, Any]
    grade: Decimal | None = None
    status: SubmissionStatus
    submitted_at: datetime
    ai_insight: SubmissionAiInsightResponse | None = None
    evaluation: SubmissionEvaluationResponse | None = None

    model_config = ConfigDict(from_attributes=True)


# Alias para retrocompatibilidade semântica
SubmissionDetailResponse = SubmissionDetailTeacherResponse


class SubmissionStatsResponse(BaseModel):
    assignment_id: UUID
    total_enrolled: int = Field(ge=0)
    total_submissions: int = Field(ge=0)
    pending: int = Field(ge=0)
    awaiting_review: int = Field(ge=0)
    ready_to_publish: int = Field(ge=0)
    published: int = Field(ge=0)
    average_grade: Decimal | None = None

    model_config = ConfigDict(from_attributes=True)
