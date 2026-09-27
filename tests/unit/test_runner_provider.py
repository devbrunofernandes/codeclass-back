from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    RunnerError,
    RunnerTimeoutError,
)
from app.models.enums import TestRunVerdict
from app.schemas.assignment import TestCaseConfig
from app.services.runner.factory import get_runner_provider
from app.services.runner.judge0_provider import Judge0Provider
from app.services.runner.piston_provider import PistonProvider


def test_factory_returns_judge0_provider() -> None:
    with patch.object(settings, "RUNNER_PROVIDER", "judge0"):
        provider = get_runner_provider()
        assert isinstance(provider, Judge0Provider)


def test_factory_returns_piston_provider() -> None:
    with patch.object(settings, "RUNNER_PROVIDER", "piston"):
        provider = get_runner_provider()
        assert isinstance(provider, PistonProvider)


def test_factory_raises_for_unsupported_provider() -> None:
    with (
        patch.object(settings, "RUNNER_PROVIDER", "unsupported_engine"),
        pytest.raises(ValueError, match="Provedor de runner não suportado"),
    ):
        get_runner_provider()


def test_judge0_language_mapping() -> None:
    provider = Judge0Provider()
    assert provider.map_language_to_id("python3") == 71
    assert provider.map_language_to_id("PYTHON") == 71
    assert provider.map_language_to_id("javascript") == 63
    assert provider.map_language_to_id("nodejs") == 63
    assert provider.map_language_to_id("typescript") == 74
    assert provider.map_language_to_id("c") == 50
    assert provider.map_language_to_id("c++") == 54
    assert provider.map_language_to_id("cpp") == 54
    assert provider.map_language_to_id("java") == 62
    assert provider.map_language_to_id("csharp") == 51
    assert provider.map_language_to_id("c#") == 51
    assert provider.map_language_to_id("go") == 60
    assert provider.map_language_to_id("rust") == 73


def test_judge0_language_mapping_unknown_raises_bad_request() -> None:
    provider = Judge0Provider()
    with pytest.raises(BadRequestException, match="não é suportada pelo executor"):
        provider.map_language_to_id("brainfuck")


def test_judge0_headers_rapidapi() -> None:
    provider = Judge0Provider()
    with (
        patch.object(settings, "RUNNER_API_URL", "https://judge0-ce.p.rapidapi.com"),
        patch.object(settings, "RUNNER_API_KEY", "secret-rapid-key"),
    ):
        headers = provider.build_headers()
        assert headers["X-RapidAPI-Key"] == "secret-rapid-key"
        assert headers["X-RapidAPI-Host"] == "judge0-ce.p.rapidapi.com"
        assert headers["Content-Type"] == "application/json"


def test_judge0_headers_self_hosted() -> None:
    provider = Judge0Provider()
    with (
        patch.object(settings, "RUNNER_API_URL", "http://localhost:2358"),
        patch.object(settings, "RUNNER_API_KEY", "auth-token"),
    ):
        headers = provider.build_headers()
        assert "X-RapidAPI-Key" not in headers
        assert headers["X-Auth-Token"] == "auth-token"
        assert headers["Content-Type"] == "application/json"


def test_judge0_status_mapping() -> None:
    provider = Judge0Provider()
    assert provider.map_status_to_verdict(3) == TestRunVerdict.ACCEPTED
    assert provider.map_status_to_verdict(4) == TestRunVerdict.WRONG_ANSWER
    assert provider.map_status_to_verdict(5) == TestRunVerdict.TIME_LIMIT_EXCEEDED
    assert provider.map_status_to_verdict(6) == TestRunVerdict.COMPILATION_ERROR
    assert provider.map_status_to_verdict(7) == TestRunVerdict.RUNTIME_ERROR
    assert provider.map_status_to_verdict(11) == TestRunVerdict.RUNTIME_ERROR
    assert provider.map_status_to_verdict(13) == TestRunVerdict.INTERNAL_ERROR
    assert provider.map_status_to_verdict(999) == TestRunVerdict.INTERNAL_ERROR


@pytest.mark.asyncio
async def test_judge0_execute_batch_success() -> None:
    provider = Judge0Provider()
    test_cases = [
        TestCaseConfig(id=1, input="2 3\n", expected_output="5\n"),
        TestCaseConfig(id=2, input="1 1\n", expected_output="2\n"),
    ]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    # Mock do POST /submissions/batch
    post_resp = httpx.Response(
        201,
        json=[{"token": "tok-1"}, {"token": "tok-2"}],
        request=httpx.Request("POST", "http://test"),
    )
    # Mock do GET /submissions/batch
    get_resp = httpx.Response(
        200,
        json={
            "submissions": [
                {
                    "token": "tok-1",
                    "status_id": 3,
                    "stdout": "5\n",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.021",
                    "memory": 10240,
                },
                {
                    "token": "tok-2",
                    "status_id": 3,
                    "stdout": "2\n",
                    "stderr": None,
                    "compile_output": None,
                    "time": "0.019",
                    "memory": 10240,
                },
            ]
        },
        request=httpx.Request("GET", "http://test"),
    )
    mock_client.post.return_value = post_resp
    mock_client.get.return_value = get_resp

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="print(sum(map(int, input().split())))",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 2
    assert results[0].test_case_id == 1
    assert results[0].status == TestRunVerdict.ACCEPTED
    assert results[0].stdout == "5\n"
    assert results[0].time_sec == 0.021
    assert results[1].test_case_id == 2
    assert results[1].status == TestRunVerdict.ACCEPTED


@pytest.mark.asyncio
async def test_judge0_execute_batch_tle_verdict_returns_time_limit_exceeded() -> None:
    provider = Judge0Provider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    post_resp = httpx.Response(
        201,
        json=[{"token": "tok-tle"}],
        request=httpx.Request("POST", "http://test"),
    )
    get_resp = httpx.Response(
        200,
        json={
            "submissions": [
                {
                    "token": "tok-tle",
                    "status_id": 5,  # Time Limit Exceeded no Judge0
                    "stdout": None,
                    "stderr": None,
                    "compile_output": None,
                    "time": "2.001",
                    "memory": 12000,
                }
            ]
        },
        request=httpx.Request("GET", "http://test"),
    )
    mock_client.post.return_value = post_resp
    mock_client.get.return_value = get_resp

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="while True: pass",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 1
    assert results[0].status == TestRunVerdict.TIME_LIMIT_EXCEEDED
    assert results[0].time_sec == 2.001


@pytest.mark.asyncio
async def test_judge0_execute_batch_http_timeout_raises_runner_timeout_error() -> None:
    provider = Judge0Provider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RunnerTimeoutError, match="demorou muito para responder"),
    ):
        await provider.execute_batch(
            code="print(1)",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )


@pytest.mark.asyncio
async def test_judge0_execute_batch_network_error_raises_runner_error() -> None:
    provider = Judge0Provider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.ConnectError("Failed to connect")

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RunnerError, match="Falha na comunicação com o executor"),
    ):
        await provider.execute_batch(
            code="print(1)",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )


def test_piston_language_mapping() -> None:
    provider = PistonProvider()
    assert provider.map_language("python3") == "python"
    assert provider.map_language("PYTHON") == "python"
    assert provider.map_language("javascript") == "javascript"
    assert provider.map_language("nodejs") == "javascript"
    assert provider.map_language("typescript") == "typescript"
    assert provider.map_language("c") == "c"
    assert provider.map_language("c++") == "c++"
    assert provider.map_language("cpp") == "c++"
    assert provider.map_language("java") == "java"
    assert provider.map_language("csharp") == "csharp"
    assert provider.map_language("c#") == "csharp"
    assert provider.map_language("go") == "go"
    assert provider.map_language("rust") == "rust"


def test_piston_language_mapping_unknown_raises_bad_request() -> None:
    provider = PistonProvider()
    with pytest.raises(BadRequestException, match="não é suportada pelo executor"):
        provider.map_language("brainfuck")


def test_piston_build_headers() -> None:
    provider = PistonProvider()
    with patch.object(settings, "RUNNER_API_KEY", ""):
        headers = provider.build_headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    with patch.object(settings, "RUNNER_API_KEY", "bearer-token"):
        headers = provider.build_headers()
        assert headers["Authorization"] == "bearer-token"


@pytest.mark.asyncio
async def test_piston_execute_batch_success() -> None:
    provider = PistonProvider()
    test_cases = [
        TestCaseConfig(id=1, input="2 3\n", expected_output="5"),
        TestCaseConfig(id=2, input="1 1\n", expected_output="2"),
    ]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    def post_side_effect(url: str, **kwargs: object) -> httpx.Response:
        data = kwargs.get("json", {})
        assert isinstance(data, dict)
        stdin = data.get("stdin")
        if stdin == "2 3\n":
            return httpx.Response(
                200,
                json={"run": {"stdout": "5\n", "stderr": "", "code": 0}},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(
            200,
            json={"run": {"stdout": "3\n", "stderr": "", "code": 0}},
            request=httpx.Request("POST", url),
        )

    mock_client.post.side_effect = post_side_effect

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="print(sum(map(int, input().split())))",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 2
    assert results[0].test_case_id == 1
    assert results[0].status == TestRunVerdict.ACCEPTED
    assert results[0].stdout == "5\n"
    assert results[1].test_case_id == 2
    assert results[1].status == TestRunVerdict.WRONG_ANSWER


@pytest.mark.asyncio
async def test_piston_execute_batch_compilation_error() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        200,
        json={
            "compile": {
                "code": 1,
                "output": "syntax error: expected semicolon",
                "stderr": "syntax error: expected semicolon",
            }
        },
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="int main() {",
            language="cpp",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 1
    assert results[0].status == TestRunVerdict.COMPILATION_ERROR
    assert results[0].compile_output == "syntax error: expected semicolon"


@pytest.mark.asyncio
async def test_piston_execute_batch_runtime_error() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        200,
        json={
            "run": {
                "code": 1,
                "stdout": "",
                "stderr": "ZeroDivisionError: division by zero",
            }
        },
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="1 / 0",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 1
    assert results[0].status == TestRunVerdict.RUNTIME_ERROR
    assert results[0].stderr == "ZeroDivisionError: division by zero"


@pytest.mark.asyncio
async def test_piston_execute_batch_tle() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        200,
        json={"run": {"signal": "SIGKILL", "stdout": "", "stderr": "Killed"}},
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="while True: pass",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 1
    assert results[0].status == TestRunVerdict.TIME_LIMIT_EXCEEDED
    assert results[0].time_sec == 2.0


@pytest.mark.asyncio
async def test_piston_execute_batch_http_errors() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        500, request=httpx.Request("POST", "http://test")
    )

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RunnerError, match="Falha na execução no Piston: HTTP 500"),
    ):
        await provider.execute_batch(
            code="1",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )


@pytest.mark.asyncio
async def test_piston_execute_batch_runtime_error_from_signal() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        200,
        json={
            "run": {
                "signal": "SIGSEGV",
                "code": None,
                "stdout": "",
                "stderr": "Segmentation fault",
            }
        },
        request=httpx.Request("POST", "http://test"),
    )

    with patch("httpx.AsyncClient", return_value=mock_client):
        results = await provider.execute_batch(
            code="int *p = 0; *p = 1;",
            language="c",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )

    assert len(results) == 1
    assert results[0].status == TestRunVerdict.RUNTIME_ERROR
    assert results[0].stderr == "Segmentation fault"


@pytest.mark.asyncio
async def test_piston_execute_batch_passes_memory_limit() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    captured_payload: dict[str, object] = {}

    def post_side_effect(url: str, **kwargs: object) -> httpx.Response:
        nonlocal captured_payload
        data = kwargs.get("json", {})
        if isinstance(data, dict):
            captured_payload = data
        return httpx.Response(
            200,
            json={"run": {"stdout": "ok", "code": 0}},
            request=httpx.Request("POST", url),
        )

    mock_client.post.side_effect = post_side_effect

    with patch("httpx.AsyncClient", return_value=mock_client):
        await provider.execute_batch(
            code="print('ok')",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=64,
        )

    assert captured_payload.get("run_memory_limit") == 64 * 1024 * 1024


@pytest.mark.asyncio
async def test_piston_execute_batch_invalid_json_raises_runner_error() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="ok")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = httpx.Response(
        200,
        content=b"<!DOCTYPE html><html>Bad Gateway</html>",
        request=httpx.Request("POST", "http://test"),
    )

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(
            RunnerError, match="Resposta inválida recebida do executor de código"
        ),
    ):
        await provider.execute_batch(
            code="print(1)",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )


@pytest.mark.asyncio
async def test_piston_execute_batch_http_timeout_raises_runner_timeout_error() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RunnerTimeoutError, match="demorou muito para responder"),
    ):
        await provider.execute_batch(
            code="print(1)",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )


@pytest.mark.asyncio
async def test_piston_execute_batch_network_error_raises_runner_error() -> None:
    provider = PistonProvider()
    test_cases = [TestCaseConfig(id=1, input="", expected_output="")]

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = httpx.ConnectError("Connection refused")

    with (
        patch("httpx.AsyncClient", return_value=mock_client),
        pytest.raises(RunnerError, match="Falha na comunicação com o executor"),
    ):
        await provider.execute_batch(
            code="print(1)",
            language="python3",
            test_cases=test_cases,
            time_limit_sec=2.0,
            memory_limit_mb=128,
        )
