from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.database import get_db
from app.core.exceptions import (
    ForbiddenException,
    UnauthorizedException,
)
from app.infrastructure.auth import auth_service
from app.models.organization import OrganizationMember
from app.models.user import User

security = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Extrai e valida o token JWT, retornando o usuário correspondente no banco local."""
    token = credentials.credentials
    payload = await auth_service.verify_jwt_token(token)

    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedException("Token inválido: sujeito não encontrado.")

    try:
        user_id = UUID(str(sub))
    except (ValueError, TypeError) as e:
        raise UnauthorizedException(
            "Identificador de usuário inválido no token."
        ) from e

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedException("Usuário não encontrado.")

    return user


async def get_current_active_member(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMember:
    """Obtém o registro de membro institucional ativo associado ao usuário autenticado."""
    stmt = (
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization))
        .where(OrganizationMember.user_id == current_user.id)
    )
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()

    if member is None:
        raise ForbiddenException("Usuário não está vinculado a nenhuma organização.")

    if not member.is_active:
        raise ForbiddenException("Acesso de usuário desativado na organização.")

    return member
