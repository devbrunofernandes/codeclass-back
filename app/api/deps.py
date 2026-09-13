from collections.abc import AsyncGenerator, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.services.auth_service import AuthError, auth_service

security = HTTPBearer(auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = credentials.credentials
    try:
        payload = await auth_service.verify_jwt_token(token)
    except AuthError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido: sujeito não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(sub))
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identificador de usuário inválido no token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    # Consulta usuário no banco local
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_active_member(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMember:
    stmt = (
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.organization))
        .where(OrganizationMember.user_id == current_user.id)
    )
    result = await db.execute(stmt)
    member = result.scalar_one_or_none()

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuário não está vinculado a nenhuma organização.",
        )

    if not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso de usuário desativado na organização.",
        )

    return member


def require_roles(*allowed_roles: OrgRole) -> Callable[..., OrganizationMember]:
    """Dependência que exige um ou mais papéis RBAC específicos."""
    def role_checker(
        member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    ) -> OrganizationMember:
        if member.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acesso negado: permissão insuficiente para executar esta ação.",
            )
        return member

    return role_checker


async def verify_org_access(
    org_id: UUID,
    member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> OrganizationMember:
    """Garante que o membro pertence estritamente à organização indicada na rota (RNF01)."""
    if member.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado a recursos de outra organização.",
        )
    return member


require_owner = require_roles(OrgRole.OWNER)
require_admin_or_owner = require_roles(OrgRole.OWNER, OrgRole.ADMIN)
require_teacher = require_roles(OrgRole.TEACHER)

__all__ = [
    "AsyncGenerator",
    "AsyncSession",
    "get_current_active_member",
    "get_current_user",
    "get_db",
    "require_admin_or_owner",
    "require_owner",
    "require_roles",
    "require_teacher",
    "verify_org_access",
]
