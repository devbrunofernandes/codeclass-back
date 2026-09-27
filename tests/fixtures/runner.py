from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import pytest

from app.infrastructure.runner.base import CodeRunnerProvider
from app.models.enums import TestRunVerdict
from app.schemas.assignment import TestCaseConfig
from app.schemas.runner import TestCaseResult


class MockRunnerProvider(CodeRunnerProvider):
    """Provedor mock de execução de código para testes determinísticos."""

    def __init__(
        self,
        default_verdict: TestRunVerdict = TestRunVerdict.ACCEPTED,
        force_error: Exception | None = None,
    ) -> None:
        self.default_verdict = default_verdict
        self.force_error = force_error
        self.invocations: list[dict[str, Any]] = []

    async def execute_batch(
        self,
        code: str,
        language: str,
        test_cases: list[TestCaseConfig],
        time_limit_sec: float,
        memory_limit_mb: int,
    ) -> list[TestCaseResult]:
        self.invocations.append(
            {
                "code": code,
                "language": language,
                "test_cases": test_cases,
                "time_limit_sec": time_limit_sec,
                "memory_limit_mb": memory_limit_mb,
            }
        )
        if self.force_error is not None:
            raise self.force_error

        results: list[TestCaseResult] = []
        for tc in test_cases:
            if self.default_verdict == TestRunVerdict.ACCEPTED:
                results.append(
                    TestCaseResult(
                        test_case_id=tc.id,
                        status=TestRunVerdict.ACCEPTED,
                        stdout=tc.expected_output,
                        stderr=None,
                        compile_output=None,
                        time_sec=0.05,
                        memory_kb=10240,
                    )
                )
            elif self.default_verdict == TestRunVerdict.WRONG_ANSWER:
                results.append(
                    TestCaseResult(
                        test_case_id=tc.id,
                        status=TestRunVerdict.WRONG_ANSWER,
                        stdout="wrong output\n",
                        stderr=None,
                        compile_output=None,
                        time_sec=0.04,
                        memory_kb=10240,
                    )
                )
            elif self.default_verdict == TestRunVerdict.TIME_LIMIT_EXCEEDED:
                results.append(
                    TestCaseResult(
                        test_case_id=tc.id,
                        status=TestRunVerdict.TIME_LIMIT_EXCEEDED,
                        stdout=None,
                        stderr=None,
                        compile_output=None,
                        time_sec=time_limit_sec,
                        memory_kb=12000,
                    )
                )
            elif self.default_verdict == TestRunVerdict.COMPILATION_ERROR:
                results.append(
                    TestCaseResult(
                        test_case_id=tc.id,
                        status=TestRunVerdict.COMPILATION_ERROR,
                        stdout=None,
                        stderr=None,
                        compile_output="SyntaxError: invalid syntax",
                        time_sec=0.0,
                        memory_kb=0,
                    )
                )
            else:
                results.append(
                    TestCaseResult(
                        test_case_id=tc.id,
                        status=self.default_verdict,
                        stdout=None,
                        stderr="Runtime execution failure",
                        compile_output=None,
                        time_sec=0.02,
                        memory_kb=5000,
                    )
                )
        return results


@pytest.fixture
def mock_runner_provider() -> MockRunnerProvider:
    """Instância base do MockRunnerProvider com veredito ACCEPTED por padrão."""
    return MockRunnerProvider()


from app.services.runner_service import runner_service


@pytest.fixture(autouse=True)
def override_runner_provider(
    mock_runner_provider: MockRunnerProvider,
) -> AsyncGenerator[MockRunnerProvider]:
    """Sobrescreve o provedor de runner em todos os testes para garantir isolamento de rede."""
    runner_service.provider = mock_runner_provider
    with patch(
        "app.infrastructure.runner.factory.get_runner_provider",
        return_value=mock_runner_provider,
    ):
        yield mock_runner_provider
    runner_service.provider = None


@pytest.fixture
def valid_test_run_payload() -> dict[str, str]:
    return {
        "language": "python3",
        "code": "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)",
    }


@pytest.fixture
def wrong_answer_test_run_payload() -> dict[str, str]:
    return {
        "language": "python3",
        "code": "print(0)",
    }


@pytest.fixture
def tle_test_run_payload() -> dict[str, str]:
    return {
        "language": "python3",
        "code": "while True: pass",
    }


@pytest.fixture
def compilation_error_test_run_payload() -> dict[str, str]:
    return {
        "language": "python3",
        "code": "def erro_sintaxe(",
    }
