import asyncio
import time
from typing import ClassVar
from urllib.parse import urlparse

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


class Judge0Provider(CodeRunnerProvider):
    """Provedor concreto de execução de código integrado à API do Judge0 CE (RapidAPI e Self-Hosted)."""

    LANGUAGE_MAP: ClassVar[dict[str, int]] = {
        "python": 71,
        "python3": 71,
        "javascript": 63,
        "js": 63,
        "nodejs": 63,
        "node": 63,
        "typescript": 74,
        "ts": 74,
        "c": 50,
        "cpp": 54,
        "c++": 54,
        "java": 62,
        "csharp": 51,
        "c#": 51,
        "cs": 51,
        "go": 60,
        "golang": 60,
        "rust": 73,
    }

    def map_language_to_id(self, language: str) -> int:
        """Mapeia o identificador amigável da linguagem para o language_id do Judge0."""
        normalized = language.strip().lower()
        lang_id = self.LANGUAGE_MAP.get(normalized)
        if lang_id is None:
            raise BadRequestException(
                f"A linguagem '{language}' não é suportada pelo executor de código."
            )
        return lang_id

    def build_headers(self) -> dict[str, str]:
        """Constrói os cabeçalhos HTTP apropriados de acordo com o endpoint (RapidAPI vs Self-Hosted)."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        api_url = settings.RUNNER_API_URL or ""
        parsed = urlparse(api_url)

        if "rapidapi.com" in parsed.netloc:
            headers["X-RapidAPI-Key"] = settings.RUNNER_API_KEY
            headers["X-RapidAPI-Host"] = parsed.netloc
        elif settings.RUNNER_API_KEY:
            headers["X-Auth-Token"] = settings.RUNNER_API_KEY

        return headers

    def map_status_to_verdict(self, status_id: int) -> TestRunVerdict:
        """Normaliza o status_id retornado pelo Judge0 para o enum TestRunVerdict."""
        if status_id == 3:
            return TestRunVerdict.ACCEPTED
        if status_id == 4:
            return TestRunVerdict.WRONG_ANSWER
        if status_id == 5:
            return TestRunVerdict.TIME_LIMIT_EXCEEDED
        if status_id == 6:
            return TestRunVerdict.COMPILATION_ERROR
        if 7 <= status_id <= 12:
            return TestRunVerdict.RUNTIME_ERROR
        return TestRunVerdict.INTERNAL_ERROR

    async def execute_batch(
        self,
        code: str,
        language: str,
        test_cases: list[TestCaseConfig],
        time_limit_sec: float,
        memory_limit_mb: int,
    ) -> list[TestCaseResult]:
        """Submete o código contra múltiplos casos de teste no Judge0 CE em lote e aguarda os resultados."""
        lang_id = self.map_language_to_id(language)
        headers = self.build_headers()
        base_url = (
            settings.RUNNER_API_URL or "https://judge0-ce.p.rapidapi.com"
        ).rstrip("/")
        timeout_limit = settings.RUNNER_TIMEOUT_SEC or 15.0

        memory_limit_kb = int(memory_limit_mb * 1024)

        submissions_payload = [
            {
                "language_id": lang_id,
                "source_code": code,
                "stdin": tc.input,
                "expected_output": tc.expected_output,
                "cpu_time_limit": time_limit_sec,
                "memory_limit": memory_limit_kb,
            }
            for tc in test_cases
        ]

        async with httpx.AsyncClient(timeout=timeout_limit) as client:
            try:
                # 1. Submissão do lote
                batch_post_url = f"{base_url}/submissions/batch?base64_encoded=false"
                resp = await client.post(
                    batch_post_url,
                    headers=headers,
                    json={"submissions": submissions_payload},
                )
                if resp.status_code not in (200, 201):
                    raise RunnerError(
                        f"Falha na comunicação com o executor de código: HTTP {resp.status_code}",
                        status_code=502,
                    )
                tokens_data = resp.json()
                tokens = [item["token"] for item in tokens_data if "token" in item]
                if not tokens or len(tokens) != len(test_cases):
                    raise RunnerError(
                        "Falha ao registrar casos de teste no executor remoto.",
                        status_code=502,
                    )

                # 2. Polling assíncrono controlado com backoff
                tokens_csv = ",".join(tokens)
                batch_get_url = (
                    f"{base_url}/submissions/batch?tokens={tokens_csv}"
                    "&base64_encoded=false&fields=token,status_id,status,stdout,stderr,compile_output,time,memory"
                )

                start_time = time.monotonic()
                submissions_results: list[dict] = []

                while True:
                    if time.monotonic() - start_time > timeout_limit:
                        raise RunnerTimeoutError(
                            "O executor de código externo demorou muito para responder.",
                            status_code=504,
                        )

                    poll_resp = await client.get(batch_get_url, headers=headers)
                    if poll_resp.status_code >= 400:
                        raise RunnerError(
                            f"Falha na consulta de status do executor: HTTP {poll_resp.status_code}",
                            status_code=502,
                        )

                    if poll_resp.status_code == 200:
                        poll_data = poll_resp.json()
                        current_results = poll_data.get("submissions", [])
                        # Status ID 1 (In Queue) e 2 (Processing)
                        is_all_finished = all(
                            item.get("status_id", 0) not in (1, 2)
                            for item in current_results
                        ) and len(current_results) == len(tokens)

                        if is_all_finished:
                            submissions_results = current_results
                            break

                    await asyncio.sleep(0.5)

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

        # 3. Mapeia resultados para a ordem original dos casos de teste
        token_to_result = {
            item["token"]: item for item in submissions_results if "token" in item
        }
        final_results: list[TestCaseResult] = []

        for idx, tc in enumerate(test_cases):
            tok = tokens[idx]
            sub_res = token_to_result.get(tok, {})
            status_id = sub_res.get("status_id", 13)
            verdict = self.map_status_to_verdict(status_id)

            raw_time = sub_res.get("time")
            time_sec = float(raw_time) if raw_time is not None else None

            raw_memory = sub_res.get("memory")
            try:
                memory_kb = int(float(raw_memory)) if raw_memory is not None else None
            except ValueError, TypeError:
                memory_kb = None

            final_results.append(
                TestCaseResult(
                    test_case_id=tc.id,
                    status=verdict,
                    stdout=sub_res.get("stdout"),
                    stderr=sub_res.get("stderr"),
                    compile_output=sub_res.get("compile_output"),
                    time_sec=time_sec,
                    memory_kb=memory_kb,
                )
            )

        return final_results
