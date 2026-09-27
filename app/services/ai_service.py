import json
import logging
from decimal import Decimal
from typing import Any

from app.infrastructure.ai import AiProvider, get_ai_provider
from app.models.assignment import Assignment
from app.models.enums import AssignmentType
from app.schemas.submission import AiInsightResult

logger = logging.getLogger(__name__)


class AiService:
    """Serviço de domínio pedagógico para geração de avaliações assistidas por IA.

    Totalmente desacoplado do provedor de IA subjacente (Strategy Pattern).
    """

    def __init__(self, provider: AiProvider | None = None) -> None:
        self._provider = provider

    @property
    def provider(self) -> AiProvider:
        if self._provider is None:
            self._provider = get_ai_provider()
        return self._provider

    async def evaluate_submission(
        self,
        assignment: Assignment,
        submission_content: dict[str, Any],
    ) -> AiInsightResult:
        """Ponto de entrada único para avaliação pedagógica de submissões com IA."""
        if assignment.type == AssignmentType.CODE:
            code = submission_content.get("code", "")
            language = submission_content.get("language", "")
            return await self.evaluate_code_submission(assignment, code, language)
        elif assignment.type == AssignmentType.QUESTIONNAIRE:
            answers = submission_content.get("answers", [])
            return await self.evaluate_questionnaire_submission(assignment, answers)
        else:
            raise ValueError(
                f"Tipo de atividade não suportado pela IA: {assignment.type}"
            )

    async def evaluate_code_submission(
        self,
        assignment: Assignment,
        code: str,
        language: str,
    ) -> AiInsightResult:
        """Gera parecer pedagógico e nota sugerida para submissão de código."""
        max_grade = float(assignment.config.get("max_grade", 10.0))
        rubrics = (
            assignment.config.get("rubrics")
            or assignment.config.get("rubric")
            or "Não informada"
        )
        test_cases = assignment.config.get("test_cases", [])

        prompt = f"""
Você é um avaliador pedagógico especialista em Ciência da Computação para a plataforma educacional CodeClass.
Sua tarefa é analisar o código submetido por um aluno para uma atividade prática de programação e gerar um feedback
pedagógico estritamente confidencial para apoiar o professor da disciplina na correção e atribuição da nota.

--- DADOS DA ATIVIDADE ---
Título: {assignment.title}
Descrição: {assignment.description or "Sem descrição adicional"}
Pontuação Máxima (Nota): {max_grade}
Rubricas / Critérios de Avaliação: {rubrics}
Casos de Teste Esperados: {json.dumps(test_cases, ensure_ascii=False) if test_cases else "Nenhum caso fornecido"}

--- SUBMISSÃO DO ALUNO ---
Linguagem: {language}
Código Submetido:
```{language}
{code}
```

--- INSTRUÇÕES DE AVALIAÇÃO ---
1. Analise o código quanto a: corretude funcional, legibilidade, boas práticas da linguagem {language}, tratamento de bordas e eficiência.
2. Atribua uma nota sugerida ('suggested_grade') proporcional entre 0.0 e {max_grade}.
3. Destaque pontos fortes ('strengths') objetivos observados no código.
4. Destaque pontos de melhoria ('improvements') pedagógicos e construtivos.
5. Forneça uma justificativa pedagógica geral ('reasoning') para embasar a decisão do professor.
6. 'item_insights' deve ser nulo (null) para atividades de código.
"""

        return await self.provider.generate_structured_insight(
            prompt=prompt,
            schema=AiInsightResult,
            temperature=0.2,
        )

    async def evaluate_questionnaire_submission(
        self,
        assignment: Assignment,
        answers: list[dict[str, Any]],
    ) -> AiInsightResult:
        """Avalia questionário com questões dissertativas, combinando cálculo determinístico e IA."""
        questions: list[dict[str, Any]] = assignment.config.get("questions", [])
        answers_by_id = {ans.get("question_id"): ans for ans in answers}

        # 1. Separa questões objetivas de dissertativas
        objective_questions = [q for q in questions if q.get("type") == "choice"]
        open_questions = [q for q in questions if q.get("type") == "open"]

        objective_score = Decimal("0.00")
        total_max_points = sum(float(q.get("points", 0.0)) for q in questions)
        if total_max_points == 0.0:
            total_max_points = float(assignment.config.get("max_grade", 10.0))

        # 2. Correção determinística das questões objetivas
        for q in objective_questions:
            qid = q.get("id")
            pts = Decimal(str(q.get("points", 0.0)))
            correct_opt = q.get("correct_option_id")
            user_ans = answers_by_id.get(qid)
            selected_opt = user_ans.get("selected_option_id") if user_ans else None
            if selected_opt and selected_opt == correct_opt:
                objective_score += pts

        # 3. Monta payload para inferência da IA sobre as questões dissertativas
        open_questions_data = []
        for q in open_questions:
            qid = q.get("id")
            user_ans = answers_by_id.get(qid)
            text_answer = (
                user_ans.get("text_answer", "") if user_ans else "(Não respondida)"
            )
            open_questions_data.append(
                {
                    "question_id": qid,
                    "statement": q.get("statement") or q.get("prompt") or "",
                    "max_points": float(q.get("points", 0.0)),
                    "reference_answer": q.get("reference_answer")
                    or q.get("expected_answer")
                    or "Não informada",
                    "student_answer": text_answer,
                }
            )

        prompt = f"""
Você é um avaliador pedagógico especialista para a plataforma educacional CodeClass.
Sua tarefa é avaliar as respostas dissertativas submetidas por um aluno em um questionário e gerar um parecer pedagógico
confidencial para o professor da disciplina.

--- DADOS DO QUESTIONÁRIO ---
Título: {assignment.title}
Descrição: {assignment.description or "Sem descrição adicional"}
Pontuação Obtida nas Questões Objetivas: {float(objective_score)}
Pontuação Máxima Total do Questionário: {total_max_points}

--- QUESTÕES DISSERTATIVAS A AVALIAR ---
{json.dumps(open_questions_data, indent=2, ensure_ascii=False)}

--- INSTRUÇÕES ---
1. Para CADA questão dissertativa, avalie a precisão conceitual e coerência com a resposta de referência.
2. Atribua em 'item_insights' para cada questão:
   - question_id
   - suggested_grade (entre 0.0 e a pontuação máxima da questão)
   - max_grade (pontuação máxima da questão)
   - strengths (pontos fortes da resposta do aluno)
   - improvements (lacunas ou pontos a melhorar)
   - reasoning (justificativa pedagógica da pontuação do item)
3. Some a pontuação obtida nas questões objetivas ({float(objective_score)}) com as notas sugeridas das questões dissertativas
   para calcular 'suggested_grade' total do questionário.
4. 'max_grade' geral deve ser exatamente {total_max_points}.
5. Forneça 'strengths' gerais, 'improvements' gerais e um parecer global ('reasoning') sobre o desempenho do aluno.
"""

        result = await self.provider.generate_structured_insight(
            prompt=prompt,
            schema=AiInsightResult,
            temperature=0.2,
        )

        # Garante que a nota total e a nota máxima combinam com precisão matemática e respeito aos limites
        if result.item_insights:
            open_score = sum(item.suggested_grade for item in result.item_insights)
            calculated_grade = round(float(objective_score) + open_score, 2)
        else:
            calculated_grade = round(float(objective_score) + result.suggested_grade, 2)

        result.suggested_grade = max(
            0.0, min(calculated_grade, float(total_max_points))
        )
        result.max_grade = total_max_points
        return result


ai_service = AiService()
