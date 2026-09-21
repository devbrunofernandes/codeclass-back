from typing import Any


class AppException(Exception):
    """Exceção base para todas as falhas de domínio e regras de negócio da aplicação."""

    def __init__(
        self,
        message: str,
        status_code: int = 400,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.headers = headers
        self.extra = extra or {}
        super().__init__(message)


class BadRequestException(AppException):
    def __init__(self, message: str = "Requisição inválida.") -> None:
        super().__init__(message=message, status_code=400)


class UnauthorizedException(AppException):
    def __init__(
        self,
        message: str = "Não autenticado ou credenciais inválidas.",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            status_code=401,
            headers=headers or {"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "Acesso negado.") -> None:
        super().__init__(message=message, status_code=403)


class NotFoundException(AppException):
    def __init__(self, message: str = "Recurso não encontrado.") -> None:
        super().__init__(message=message, status_code=404)


class ConflictException(AppException):
    def __init__(self, message: str = "Conflito de dados.") -> None:
        super().__init__(message=message, status_code=409)


class ValidationException(AppException):
    def __init__(self, message: str = "Erro de validação.") -> None:
        super().__init__(message=message, status_code=422)


class StorageError(AppException):
    """Exceção originada na comunicação ou operação do provedor de armazenamento."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message=message, status_code=status_code)


class AuthError(AppException):
    """Exceção originada na comunicação ou operação do provedor de autenticação."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message=message, status_code=status_code)
