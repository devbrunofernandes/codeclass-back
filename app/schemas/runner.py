from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import TestRunVerdict


class TestRunRequest(BaseModel):
    """Payload de envio para execução experimental de código (Test-Run)."""

    __test__ = False
    language: str = Field(
        min_length=1,
        max_length=50,
        description="Identificador da linguagem de programação (ex: python3, javascript).",
    )
    code: str = Field(
        min_length=1,
        description="Código-fonte do estudante a ser avaliado contra os casos de teste.",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class TestCaseResult(BaseModel):
    """Resultado individual da execução contra um caso de teste específico."""

    __test__ = False  # Evita captura indevida pelo coletor do Pytest
    test_case_id: int = Field(ge=1, description="Identificador do caso de teste.")
    status: TestRunVerdict = Field(
        description="Veredito retornado para este caso de teste."
    )
    stdout: str | None = Field(
        default=None, description="Saída padrão gerada pela execução."
    )
    stderr: str | None = Field(
        default=None, description="Saída de erro gerada pela execução."
    )
    compile_output: str | None = Field(
        default=None, description="Saída do compilador, caso ocorra erro de compilação."
    )
    time_sec: float | None = Field(
        default=None, ge=0, description="Tempo de execução do processo em segundos."
    )
    memory_kb: int | None = Field(
        default=None, ge=0, description="Consumo de memória do processo em kilobytes."
    )

    model_config = ConfigDict(from_attributes=True)


class TestRunResponse(BaseModel):
    """Resposta consolidada da execução experimental de código (efêmera)."""

    __test__ = False  # Evita captura indevida pelo coletor do Pytest
    overall_status: TestRunVerdict = Field(
        description="Veredito consolidado de todos os casos de teste (ACCEPTED se todos passarem)."
    )
    total_tests: int = Field(
        ge=0, description="Quantidade total de casos de teste avaliados."
    )
    passed_tests: int = Field(
        ge=0, description="Quantidade de casos de teste aprovados (ACCEPTED)."
    )
    execution_time_ms: float = Field(
        ge=0, description="Tempo total de processamento da requisição em milissegundos."
    )
    results: list[TestCaseResult] = Field(
        default_factory=list,
        description="Lista detalhada dos resultados de cada caso de teste.",
    )

    model_config = ConfigDict(from_attributes=True)
