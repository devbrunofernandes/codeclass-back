from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_member, get_current_user, get_db
from app.core.exceptions import ForbiddenException
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.user import (
    CurrentUserProfileResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
)
from app.services.auth_service import auth_service

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Autenticação de usuário com email e senha",
)
async def login(
    request: UserLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    auth_data = await auth_service.sign_in_with_password(
        email=request.email, password=request.password
    )

    user_id = auth_data["user_id"]

    # Consulta usuário no banco local
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise ForbiddenException("Usuário não possui vínculo com nenhuma organização.")

    # Consulta vínculo organizacional
    member_res = await db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id)
    )
    member = member_res.scalar_one_or_none()

    if member is None:
        raise ForbiddenException("Usuário não possui vínculo com nenhuma organização.")

    if not member.is_active:
        raise ForbiddenException("Acesso de usuário desativado na organização.")

    return TokenResponse(
        access_token=auth_data["access_token"],
        refresh_token=auth_data.get("refresh_token"),
        token_type="bearer",
        user=UserResponse.model_validate(user),
        role=member.role,
        organization_id=member.organization_id,
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    summary="Renova token de acesso a partir do refresh token",
)
async def refresh_token(request: RefreshTokenRequest) -> RefreshTokenResponse:
    session_data = await auth_service.refresh_session(request.refresh_token)
    return RefreshTokenResponse(
        access_token=session_data["access_token"],
        refresh_token=session_data.get("refresh_token"),
        token_type="bearer",
    )


@router.get(
    "/me",
    response_model=CurrentUserProfileResponse,
    summary="Consulta o perfil completo e vínculo do usuário autenticado",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> CurrentUserProfileResponse:
    return CurrentUserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        created_at=current_user.created_at,
        role=current_member.role,
        is_active=current_member.is_active,
        organization_id=current_member.organization_id,
        organization_name=current_member.organization.name,
        organization_slug=current_member.organization.slug,
    )
