import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)
from app.main import app


def test_exception_instantiation_when_using_defaults_should_have_correct_status_codes() -> (
    None
):
    # Arrange & Act & Assert
    bad_request = BadRequestException()
    assert bad_request.status_code == 400
    assert bad_request.message == "Requisição inválida."

    unauthorized = UnauthorizedException()
    assert unauthorized.status_code == 401
    assert unauthorized.message == "Não autenticado ou credenciais inválidas."
    assert unauthorized.headers == {"WWW-Authenticate": "Bearer"}

    forbidden = ForbiddenException()
    assert forbidden.status_code == 403
    assert forbidden.message == "Acesso negado."

    not_found = NotFoundException()
    assert not_found.status_code == 404
    assert not_found.message == "Recurso não encontrado."

    conflict = ConflictException()
    assert conflict.status_code == 409
    assert conflict.message == "Conflito de dados."

    validation = ValidationException()
    assert validation.status_code == 422
    assert validation.message == "Erro de validação."

    custom_app_exc = AppException(
        message="Erro customizado", status_code=418, headers={"X-Teapot": "true"}
    )
    assert custom_app_exc.status_code == 418
    assert custom_app_exc.message == "Erro customizado"
    assert custom_app_exc.headers == {"X-Teapot": "true"}


@pytest.mark.anyio
async def test_global_exception_handler_when_app_exception_raised_should_return_json_detail() -> (
    None
):
    # Arrange
    # Registra uma rota efêmera de teste que dispara AppException
    @app.get("/test-app-exception-trigger")
    async def trigger_exception() -> None:
        raise ConflictException("Falha proposital de conflito para teste.")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Act
        response = await client.get("/test-app-exception-trigger")

        # Assert
        assert response.status_code == 409
        body = response.json()
        assert body == {"detail": "Falha proposital de conflito para teste."}


@pytest.mark.anyio
async def test_global_exception_handler_when_app_exception_has_extra_should_return_extra_in_json() -> (
    None
):
    # Arrange
    @app.get("/test-app-exception-extra-trigger")
    async def trigger_exception_with_extra() -> None:
        raise AppException(
            message="Erro com metadados adicionais.",
            status_code=400,
            extra={"field": "code", "issues": ["Syntax error on line 4"]},
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Act
        response = await client.get("/test-app-exception-extra-trigger")

        # Assert
        assert response.status_code == 400
        body = response.json()
        assert body == {
            "detail": "Erro com metadados adicionais.",
            "extra": {"field": "code", "issues": ["Syntax error on line 4"]},
        }
