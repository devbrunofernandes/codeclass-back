import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import AppException, ConflictException
from app.main import app


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
