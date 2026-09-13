from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_member, get_current_user, get_db
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
from app.services.auth_service import AuthError, auth_service

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
    try:
        auth_data = await auth_service.sign_in_with_password(
            email=request.email, password=request.password
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    user_id = auth_data["user_id"]

    # Consulta usuário no banco local
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Lazy sync se necessário
        user = User(
            id=user_id,
            email=auth_data["email"],
            full_name=auth_data["full_name"] or auth_data["email"].split("@")[0],
        )
        try:
            db.add(user)
            await db.commit()
            await db.refresh(user)
        except IntegrityError:
            await db.rollback()
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one()

    # Consulta vínculo organizacional
    member_res = await db.execute(
        select(OrganizationMember).where(OrganizationMember.user_id == user.id)
    )
    member = member_res.scalar_one_or_none()

    if member is not None and not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso de usuário desativado na organização.",
        )

    return TokenResponse(
        access_token=auth_data["access_token"],
        refresh_token=auth_data.get("refresh_token"),
        token_type="bearer",
        user=UserResponse.model_validate(user),
        role=member.role if member else None,
        organization_id=member.organization_id if member else None,
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    summary="Renova token de acesso a partir do refresh token",
)
async def refresh_token(request: RefreshTokenRequest) -> RefreshTokenResponse:
    try:
        session_data = await auth_service.refresh_session(request.refresh_token)
        return RefreshTokenResponse(
            access_token=session_data["access_token"],
            refresh_token=session_data.get("refresh_token"),
            token_type="bearer",
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


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
        organization_id=current_member.organization_id,
        organization_name=current_member.organization.name,
        organization_slug=current_member.organization.slug,
        role=current_member.role,
        is_active=current_member.is_active,
        created_at=current_user.created_at,
    )
