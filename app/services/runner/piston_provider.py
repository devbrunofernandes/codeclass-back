import asyncio
from typing import ClassVar

import httpx

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    RunnerError,
    RunnerTimeoutError,
)
from app.models.enums import TestRunVerdict
from app.schemas.assignment import TestCaseConfig
from app.schemas.runner import TestCaseResult
from app.services.runner.base import CodeRunnerProvider


class PistonProvider(CodeRunnerProvider):
    """Provedor de execução de código integrado à API do Piston (Container Docker Local ou Remoto)."""

    LANGUAGE_MAP: ClassVar[dict[str, str]] = {
        "python": "python",
        "python3": "python",
        "javascript": "javascript",
        "js": "javascript",
        "nodejs": "javascript",
        "node": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "c": "c",
        "cpp": "c++",
        "c++": "c++",
        "java": "java",
        "csharp": "csharp",
        "c#": "csharp",
        "cs": "csharp",
        "go": "go",
        "golang": "go",
        "rust": "rust",
    }

    def map_language(self, language: str) -> str:
        """Mapeia o identificador amigável da linguagem para a linguagem correspondente no Piston."""
        normalized = language.strip().lower()
        lang_name = self.LANGUAGE_MAP.get(normalized)
        if lang_name is None:
            raise BadRequestException(
                f"A linguagem '{language}' não é suportada pelo executor de código."
            )
        return lang_name

    def build_headers(self) -> dict[str, str]:
        """Constrói os cabeçalhos HTTP necessários para comunicação com o Piston."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if settings.RUNNER_API_KEY:
            headers["Authorization"] = settings.RUNNER_API_KEY
        return headers

    async def _execute_single_test_case(
        self,
        client: httpx.AsyncClient,
        execute_url: str,
        headers: dict[str, str],
        code: str,
        piston_lang: str,
        tc: TestCaseConfig,
        time_limit_sec: float,
        memory_limit_mb: int | None = None,
    ) -> TestCaseResult:
        """Executa um caso de teste individual contra o Piston e interpreta o veredito."""
        payload: dict[str, object] = {
            "language": piston_lang,
            "version": "*",
            "files": [{"content": code}],
            "stdin": tc.input,
            "run_timeout": int(time_limit_sec * 1000),
        }
        if memory_limit_mb and memory_limit_mb > 0:
            payload["run_memory_limit"] = int(memory_limit_mb * 1024 * 1024)

        resp = await client.post(execute_url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RunnerError(
                f"Falha na execução no Piston: HTTP {resp.status_code}",
                status_code=502,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise RunnerError(
                "Resposta inválida recebida do executor de código.",
                status_code=502,
            ) from exc

        compile_data = data.get("compile") or {}
        run_data = data.get("run") or {}

        # 1. Checa erro de compilação
        compile_code = compile_data.get("code")
        if compile_code is not None and compile_code != 0:
            return TestCaseResult(
                test_case_id=tc.id,
                status=TestRunVerdict.COMPILATION_ERROR,
                stdout=None,
                stderr=compile_data.get("stderr"),
                compile_output=compile_data.get("output"),
                time_sec=0.0,
                memory_kb=0,
            )

        run_signal = run_data.get("signal")
        run_code = run_data.get("code")
        stdout = run_data.get("stdout", "")
        stderr = run_data.get("stderr", "")

        # 2. Checa Time Limit Exceeded (SIGKILL ou timeout sinalizado)
        if run_signal in ("SIGKILL", "SIGTERM", "SIGXCPU"):
            return TestCaseResult(
                test_case_id=tc.id,
                status=TestRunVerdict.TIME_LIMIT_EXCEEDED,
                stdout=stdout if stdout else None,
                stderr=stderr if stderr else None,
                time_sec=time_limit_sec,
                memory_kb=None,
            )

        # 3. Checa Runtime Error: código de retorno diferente de 0 OU sinal anormal (não-timeout)
        if (run_code is not None and run_code != 0) or (
            run_signal is not None
            and run_signal not in ("SIGKILL", "SIGTERM", "SIGXCPU")
        ):
            return TestCaseResult(
                test_case_id=tc.id,
                status=TestRunVerdict.RUNTIME_ERROR,
                stdout=stdout if stdout else None,
                stderr=stderr if stderr else None,
                time_sec=None,
                memory_kb=None,
            )

        # 4. Avalia saída contra a saída esperada (ACCEPTED ou WRONG_ANSWER)
        actual_normalized = (stdout or "").rstrip()
        expected_normalized = (tc.expected_output or "").rstrip()

        if actual_normalized == expected_normalized:
            verdict = TestRunVerdict.ACCEPTED
        else:
            verdict = TestRunVerdict.WRONG_ANSWER

        return TestCaseResult(
            test_case_id=tc.id,
            status=verdict,
            stdout=stdout,
            stderr=stderr if stderr else None,
            time_sec=None,
            memory_kb=None,
        )

    async def execute_batch(
        self,
        code: str,
        language: str,
        test_cases: list[TestCaseConfig],
        time_limit_sec: float,
        memory_limit_mb: int,
    ) -> list[TestCaseResult]:
        """Executa todos os casos de teste de forma assíncrona concorrente contra a API do Piston."""
        piston_lang = self.map_language(language)
        headers = self.build_headers()
        base_url = (settings.RUNNER_API_URL or "http://localhost:2000").rstrip("/")
        execute_url = f"{base_url}/api/v2/execute"
        timeout_limit = settings.RUNNER_TIMEOUT_SEC or 15.0

        async with httpx.AsyncClient(timeout=timeout_limit) as client:
            try:
                tasks = [
                    self._execute_single_test_case(
                        client=client,
                        execute_url=execute_url,
                        headers=headers,
                        code=code,
                        piston_lang=piston_lang,
                        tc=tc,
                        time_limit_sec=time_limit_sec,
                        memory_limit_mb=memory_limit_mb,
                    )
                    for tc in test_cases
                ]
                return await asyncio.gather(*tasks)

            except httpx.TimeoutException as exc:
                raise RunnerTimeoutError(
                    "O executor de código externo demorou muito para responder.",
                    status_code=504,
                ) from exc
            except (httpx.ConnectError, httpx.NetworkError) as exc:
                raise RunnerError(
                    "Falha na comunicação com o executor de código.",
                    status_code=502,
                ) from exc
