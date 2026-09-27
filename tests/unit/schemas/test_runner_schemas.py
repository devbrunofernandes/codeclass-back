import pytest
from pydantic import ValidationError

from app.models.enums import TestRunVerdict
from app.schemas.runner import TestCaseResult, TestRunRequest, TestRunResponse


def test_test_run_request_valid() -> None:
    req = TestRunRequest(language="python3", code="print('hello')")
    assert req.language == "python3"
    assert req.code == "print('hello')"


def test_test_run_request_strip_whitespace() -> None:
    req = TestRunRequest(language="  python3  ", code="print(1)")
    assert req.language == "python3"


def test_test_run_request_empty_fields_should_raise_validation_error() -> None:
    with pytest.raises(ValidationError):
        TestRunRequest(language="", code="print(1)")

    with pytest.raises(ValidationError):
        TestRunRequest(language="python3", code="")


def test_test_case_result_valid() -> None:
    result = TestCaseResult(
        test_case_id=1,
        status=TestRunVerdict.ACCEPTED,
        stdout="5\n",
        stderr=None,
        compile_output=None,
        time_sec=0.04,
        memory_kb=1024,
    )
    assert result.test_case_id == 1
    assert result.status == TestRunVerdict.ACCEPTED
    assert result.stdout == "5\n"
    assert result.time_sec == 0.04


def test_test_case_result_invalid_id() -> None:
    with pytest.raises(ValidationError):
        TestCaseResult(
            test_case_id=0,
            status=TestRunVerdict.ACCEPTED,
        )


def test_test_run_response_valid() -> None:
    item = TestCaseResult(
        test_case_id=1,
        status=TestRunVerdict.ACCEPTED,
        stdout="42\n",
    )
    resp = TestRunResponse(
        overall_status=TestRunVerdict.ACCEPTED,
        total_tests=1,
        passed_tests=1,
        execution_time_ms=120.5,
        results=[item],
    )
    assert resp.overall_status == TestRunVerdict.ACCEPTED
    assert resp.total_tests == 1
    assert resp.passed_tests == 1
    assert resp.execution_time_ms == 120.5
    assert len(resp.results) == 1
