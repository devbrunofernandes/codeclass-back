"""Algoritmo determinístico e puro de correção de questionários objetivos."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QuestionEvaluationItem(BaseModel):
    """Item avaliado de uma questão do questionário."""

    question_id: int = Field(ge=1)
    type: Literal["choice", "open"] | str = "choice"
    awarded_points: float = Field(ge=0.0)
    max_points: float = Field(ge=0.0)
    is_correct: bool | None = None
    teacher_feedback: str | None = None

    model_config = ConfigDict(extra="ignore")


class QuestionnaireGradingResult(BaseModel):
    """Resultado consolidado da correção determinística de questões objetivas."""

    total_points: Decimal = Field(default=Decimal("0.00"))
    questions_evaluation: list[QuestionEvaluationItem] = Field(default_factory=list)

    @property
    def detailed_scores(self) -> dict[str, Any]:
        """Retorna estrutura serializável de detailed_scores com questions_evaluation."""
        return {
            "questions_evaluation": [
                item.model_dump(exclude_none=True) for item in self.questions_evaluation
            ]
        }

    def as_tuple(self) -> tuple[Decimal, dict[str, Any]]:
        """Retorna tupla (total_points, detailed_scores)."""
        return self.total_points, self.detailed_scores

    model_config = ConfigDict(arbitrary_types_allowed=True)


class QuestionnaireGrader:
    """Componente utilitário puro e determinístico para pontuação de questões objetivas."""

    @classmethod
    def grade_objective(
        cls,
        questions: list[dict[str, Any]] | list[Any],
        answers: list[dict[str, Any]] | list[Any],
    ) -> QuestionnaireGradingResult:
        """Calcula a nota e detalhamento de cada questão de múltipla escolha (type == 'choice').

        Ignora questões dissertativas (open) e pontua estritamente com base no gabarito
        (correct_option_id). Caso o aluno não tenha respondido uma questão, atribui nota 0.00.
        """
        # Mapeia respostas de alunos indexadas por question_id
        answers_by_id: dict[int, Any] = {}
        for ans in answers:
            if isinstance(ans, dict):
                qid = ans.get("question_id")
            else:
                qid = getattr(ans, "question_id", None)
            if qid is not None:
                answers_by_id[int(qid)] = ans

        total_points = Decimal("0.00")
        questions_eval: list[QuestionEvaluationItem] = []

        for q in questions:
            if isinstance(q, dict):
                q_type = q.get("type", "choice")
                qid = q.get("id")
                points_val = q.get("points", 0.0)
                correct_opt = q.get("correct_option_id")
            else:
                q_type = getattr(q, "type", "choice")
                qid = getattr(q, "id", None)
                points_val = getattr(q, "points", 0.0)
                correct_opt = getattr(q, "correct_option_id", None)

            # Filtra exclusivamente questões objetivas
            if q_type != "choice" or qid is None:
                continue

            max_points = Decimal(str(points_val or 0.0))
            user_ans = answers_by_id.get(int(qid))

            if user_ans is not None:
                if isinstance(user_ans, dict):
                    selected_opt = user_ans.get("selected_option_id")
                else:
                    selected_opt = getattr(user_ans, "selected_option_id", None)
            else:
                selected_opt = None

            is_correct = bool(
                selected_opt is not None and str(selected_opt) == str(correct_opt)
            )
            awarded = max_points if is_correct else Decimal("0.00")
            total_points += awarded

            questions_eval.append(
                QuestionEvaluationItem(
                    question_id=int(qid),
                    type="choice",
                    awarded_points=float(awarded),
                    max_points=float(max_points),
                    is_correct=is_correct,
                    teacher_feedback=None,
                )
            )

        return QuestionnaireGradingResult(
            total_points=total_points.quantize(Decimal("0.01")),
            questions_evaluation=questions_eval,
        )
