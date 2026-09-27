from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssignmentType, ReleasePolicyType

# --- Modelos de Configuração do Docente (Com Gabarito e Rubricas) ---


class LanguageConfig(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    starter_code: str = ""


class TestCaseConfig(BaseModel):
    __test__ = False
    id: int = Field(ge=1)
    input: str
    expected_output: str


class CodeAssignmentConfig(BaseModel):
    languages: list[LanguageConfig] = Field(min_length=1)
    time_limit_sec: float = Field(default=2.0, gt=0, le=60.0)
    memory_limit_mb: int = Field(default=128, gt=0, le=1024)
    rubric: str = Field(default="")
    test_cases: list[TestCaseConfig] = Field(default_factory=list)


class ChoiceOptionConfig(BaseModel):
    id: str = Field(min_length=1, max_length=10)
    text: str = Field(min_length=1)


class ChoiceQuestionConfig(BaseModel):
    id: int = Field(ge=1)
    type: Literal["choice"] = "choice"
    points: float = Field(ge=0)
    statement: str = Field(min_length=1)
    options: list[ChoiceOptionConfig] = Field(min_length=2)
    correct_option_id: str

    @model_validator(mode="after")
    def validate_correct_option(self) -> ChoiceQuestionConfig:
        valid_ids = {opt.id for opt in self.options}
        if self.correct_option_id not in valid_ids:
            raise ValueError(
                f"correct_option_id '{self.correct_option_id}' não coincide com nenhuma opção."
            )
        return self


class OpenQuestionConfig(BaseModel):
    id: int = Field(ge=1)
    type: Literal["open"] = "open"
    points: float = Field(ge=0)
    statement: str = Field(min_length=1)
    reference_answer: str = Field(default="")
    rubric: str = Field(default="")


QuestionConfig = Annotated[
    ChoiceQuestionConfig | OpenQuestionConfig, Field(discriminator="type")
]


class QuestionnaireAssignmentConfig(BaseModel):
    questions: list[QuestionConfig] = Field(min_length=1)


# --- Modelos de Configuração Sanitizados para Estudantes (HLD 9.4) ---


class CodeAssignmentStudentConfig(BaseModel):
    languages: list[LanguageConfig]
    time_limit_sec: float
    memory_limit_mb: int
    test_cases: list[TestCaseConfig]


class ChoiceQuestionStudentConfig(BaseModel):
    id: int
    type: Literal["choice"] = "choice"
    points: float
    statement: str
    options: list[ChoiceOptionConfig]


class OpenQuestionStudentConfig(BaseModel):
    id: int
    type: Literal["open"] = "open"
    points: float
    statement: str


QuestionStudentConfig = Annotated[
    ChoiceQuestionStudentConfig | OpenQuestionStudentConfig, Field(discriminator="type")
]


class QuestionnaireAssignmentStudentConfig(BaseModel):
    questions: list[QuestionStudentConfig]


# --- Modelos de Requisição ---


class AssignmentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    type: AssignmentType
    release_policy: ReleasePolicyType = ReleasePolicyType.ON_REVIEW
    deadline: datetime | None = None
    config: CodeAssignmentConfig | QuestionnaireAssignmentConfig

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def validate_config_before(cls, data: Any) -> Any:
        if isinstance(data, dict):
            type_val = data.get("type")
            config_val = data.get("config")
            if type_val in (AssignmentType.CODE, "code") and isinstance(
                config_val, dict
            ):
                data["config"] = CodeAssignmentConfig.model_validate(config_val)
            elif type_val in (
                AssignmentType.QUESTIONNAIRE,
                "questionnaire",
            ) and isinstance(config_val, dict):
                data["config"] = QuestionnaireAssignmentConfig.model_validate(
                    config_val
                )
        return data

    @model_validator(mode="after")
    def validate_config_type(self) -> AssignmentCreateRequest:
        if self.type == AssignmentType.CODE and not isinstance(
            self.config, CodeAssignmentConfig
        ):
            raise ValueError(
                "O campo 'config' deve seguir o formato de atividade de código."
            )
        if self.type == AssignmentType.QUESTIONNAIRE and not isinstance(
            self.config, QuestionnaireAssignmentConfig
        ):
            raise ValueError("O campo 'config' deve seguir o formato de questionário.")

        # Validação semântica de Release Policy conforme diretrizes pedagógicas
        if self.release_policy == ReleasePolicyType.IMMEDIATE:
            if self.type == AssignmentType.CODE:
                raise ValueError(
                    "A política de liberação imediata ('immediate') não é permitida para atividades de código, pois exigem avaliação docente."
                )
            if (
                self.type == AssignmentType.QUESTIONNAIRE
                and isinstance(self.config, QuestionnaireAssignmentConfig)
                and any(q.type == "open" for q in self.config.questions)
            ):
                raise ValueError(
                    "A política de liberação imediata ('immediate') é restrita a questionários 100% objetivos (sem questões dissertativas)."
                )
        return self


class AssignmentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    release_policy: ReleasePolicyType | None = None
    deadline: datetime | None = None
    config: (
        CodeAssignmentConfig | QuestionnaireAssignmentConfig | dict[str, Any] | None
    ) = None

    model_config = ConfigDict(str_strip_whitespace=True)


# --- Modelos de Resposta ---


class AssignmentTeacherResponse(BaseModel):
    id: UUID
    classroom_id: UUID
    title: str
    description: str
    type: AssignmentType
    release_policy: ReleasePolicyType
    deadline: datetime | None
    config: CodeAssignmentConfig | QuestionnaireAssignmentConfig | dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssignmentStudentResponse(BaseModel):
    id: UUID
    classroom_id: UUID
    title: str
    description: str
    type: AssignmentType
    release_policy: ReleasePolicyType
    deadline: datetime | None
    config: CodeAssignmentStudentConfig | QuestionnaireAssignmentStudentConfig
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def sanitize_student_config(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cfg = data.get("config")
            typ = data.get("type")
        else:
            cfg = getattr(data, "config", None)
            typ = getattr(data, "type", None)

        if cfg is not None:
            raw_cfg = cfg if isinstance(cfg, dict) else cfg.model_dump()
            parsed_cfg: (
                CodeAssignmentStudentConfig
                | QuestionnaireAssignmentStudentConfig
                | dict[str, Any]
            )
            if typ in (AssignmentType.CODE, "code"):
                parsed_cfg = CodeAssignmentStudentConfig.model_validate(raw_cfg)
            elif typ in (AssignmentType.QUESTIONNAIRE, "questionnaire"):
                parsed_cfg = QuestionnaireAssignmentStudentConfig.model_validate(
                    raw_cfg
                )
            else:
                parsed_cfg = raw_cfg

            if isinstance(data, dict):
                return {**data, "config": parsed_cfg}
            return {
                "id": data.id,
                "classroom_id": data.classroom_id,
                "title": data.title,
                "description": data.description,
                "type": data.type,
                "release_policy": data.release_policy,
                "deadline": data.deadline,
                "config": parsed_cfg,
                "created_at": data.created_at,
            }
        return data
