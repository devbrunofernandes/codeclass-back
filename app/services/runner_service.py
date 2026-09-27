import time
from typing import Any

from app.core.exceptions import BadRequestException
from app.infrastructure.runner.factory import get_runner_provider
from app.models.assignment import Assignment
from app.models.enums import AssignmentType, TestRunVerdict
from app.schemas.assignment import TestCaseConfig
from app.schemas.runner import TestCaseResult, TestRunRequest, TestRunResponse


class RunnerService:
    """Serviço de domínio para orquestração da execução experimental de código (Test-Run)."""

    def __init__(self, provider: Any | None = None) -> None:
        self.provider = provider

    def get_provider(self) -> Any:
        if self.provider is not None:
            return self.provider
        return get_runner_provider()

    async def execute_test_run(
        self,
        assignment: Assignment,
        request: TestRunRequest,
    ) -> TestRunResponse:
        """Valida a atividade, executa o código contra os casos de teste cadastrados via provedor configurado

        e retorna os vereditos normalizados de forma efêmera.
        """
        # 1. Valida se a atividade é do tipo código
        if assignment.type != AssignmentType.CODE:
            raise BadRequestException(
                "Apenas atividades do tipo código suportam execução experimental."
            )

        # 2. Carrega configuração da tarefa
        config: dict[str, Any] = (
            assignment.config.model_dump()
            if hasattr(assignment.config, "model_dump")
            else (assignment.config or {})
        )

        # 3. Valida se a linguagem enviada é permitida para a atividade
        allowed_languages = [
            lang.strip().lower()
            if isinstance(lang, str)
            else lang.get("name", "").strip().lower()
            for lang in config.get("languages", [])
        ]
        requested_lang = request.language.strip().lower()

        if allowed_languages and requested_lang not in allowed_languages:
            raise BadRequestException(
                f"Linguagem '{request.language}' não é permitida para esta atividade."
            )

        # 4. Valida se existem casos de teste configurados
        raw_test_cases = config.get("test_cases", [])
        if not raw_test_cases:
            raise BadRequestException(
                "Esta atividade não possui casos de teste configurados para execução."
            )

        test_cases: list[TestCaseConfig] = [
            TestCaseConfig.model_validate(tc) for tc in raw_test_cases
        ]

        time_limit_sec = float(config.get("time_limit_sec", 2.0))
        memory_limit_mb = int(config.get("memory_limit_mb", 128))

        # 5. Obtém o provedor configurado e dispara a execução
        provider = self.get_provider()
        start_time = time.perf_counter()

        results: list[TestCaseResult] = await provider.execute_batch(
            code=request.code,
            language=request.language,
            test_cases=test_cases,
            time_limit_sec=time_limit_sec,
            memory_limit_mb=memory_limit_mb,
        )

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # 6. Agrega veredito geral e métricas
        passed_count = sum(1 for r in results if r.status == TestRunVerdict.ACCEPTED)
        total_count = len(results)

        if passed_count == total_count and total_count > 0:
            overall_status = TestRunVerdict.ACCEPTED
        else:
            # Seleciona o primeiro veredito com falha para sintetizar o erro principal
            first_failed = next(
                (r for r in results if r.status != TestRunVerdict.ACCEPTED), None
            )
            overall_status = (
                first_failed.status if first_failed else TestRunVerdict.INTERNAL_ERROR
            )

        return TestRunResponse(
            overall_status=overall_status,
            total_tests=total_count,
            passed_tests=passed_count,
            execution_time_ms=round(elapsed_ms, 2),
            results=results,
        )


runner_service = RunnerService()
