from abc import ABC, abstractmethod

from app.schemas.assignment import TestCaseConfig
from app.schemas.runner import TestCaseResult


class CodeRunnerProvider(ABC):
    """Interface abstrata (Strategy Pattern) para executores de código."""

    @abstractmethod
    async def execute_batch(
        self,
        code: str,
        language: str,
        test_cases: list[TestCaseConfig],
        time_limit_sec: float,
        memory_limit_mb: int,
    ) -> list[TestCaseResult]:
        """Submete o código contra múltiplos casos de teste e devolve os resultados normalizados."""
