from app.core.exceptions import (
    AppException,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
    ValidationException,
)


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
