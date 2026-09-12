import enum


class OrgRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class AssignmentType(str, enum.Enum):
    CODE = "code"
    QUESTIONNAIRE = "questionnaire"


class ReleasePolicyType(str, enum.Enum):
    IMMEDIATE = "immediate"
    ON_REVIEW = "on_review"


class SubmissionStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    AWAITING_REVIEW = "awaiting_review"
    PUBLISHED = "published"
