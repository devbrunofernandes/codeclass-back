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


class TestRunVerdict(str, enum.Enum):
    __test__ = False
    ACCEPTED = "ACCEPTED"
    WRONG_ANSWER = "WRONG_ANSWER"
    TIME_LIMIT_EXCEEDED = "TIME_LIMIT_EXCEEDED"
    COMPILATION_ERROR = "COMPILATION_ERROR"
    RUNTIME_ERROR = "RUNTIME_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
