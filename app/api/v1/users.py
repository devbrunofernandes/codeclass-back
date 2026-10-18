from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_member, get_current_user, get_db
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.organization import OrganizationMemberResponse
from app.schemas.user import (
    CurrentUserProfileResponse,
    ProfilePhotoResponse,
    UserPasswordChangeRequest,
    UserProfileUpdateRequest,
)
from app.services.storage_service import storage_service
from app.services.user_service import user_service

router = APIRouter()


@router.get(
    "/me",
    response_model=CurrentUserProfileResponse,
    summary="Consulta o perfil completo e vínculo do usuário autenticado",
)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> CurrentUserProfileResponse:
    photos = await storage_service.get_profile_photo_fields(
        current_member.organization_id,
        {current_user.id: current_user.profile_photo_path},
    )
    return CurrentUserProfileResponse(
        **photos[current_user.id].model_dump(),
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


@router.patch(
    "/me",
    response_model=CurrentUserProfileResponse,
    summary="Atualiza dados cadastrais do próprio perfil",
)
async def update_my_profile(
    request: UserProfileUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CurrentUserProfileResponse:
    updated_user = await user_service.update_profile(
        user=current_user,
        full_name=request.full_name,
        db=db,
    )
    photos = await storage_service.get_profile_photo_fields(
        current_member.organization_id,
        {updated_user.id: updated_user.profile_photo_path},
    )

    return CurrentUserProfileResponse(
        **photos[updated_user.id].model_dump(),
        id=updated_user.id,
        email=updated_user.email,
        full_name=updated_user.full_name,
        organization_id=current_member.organization_id,
        organization_name=current_member.organization.name,
        organization_slug=current_member.organization.slug,
        role=current_member.role,
        is_active=current_member.is_active,
        created_at=updated_user.created_at,
    )


@router.put(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Altera a senha do usuário autenticado",
)
async def update_my_password(
    request: UserPasswordChangeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    _current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
) -> Response:
    await user_service.change_password(
        user_id=current_user.id,
        password=request.password,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/me/photo", response_model=ProfilePhotoResponse)
async def upload_my_photo(
    file: UploadFile,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfilePhotoResponse:
    path = await user_service.upload_profile_photo(
        current_member.user_id, current_member.organization_id, file, db
    )
    photos = await storage_service.get_profile_photo_fields(
        current_member.organization_id, {current_member.user_id: path}
    )
    return photos[current_member.user_id]


@router.get("/me/photo/download", response_model=ProfilePhotoResponse)
async def download_my_photo(
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfilePhotoResponse:
    return await user_service.download_profile_photo(
        current_member.user_id, current_member.organization_id, db
    )


@router.get("/{user_id}/photo/download", response_model=ProfilePhotoResponse)
async def download_user_photo(
    user_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProfilePhotoResponse:
    return await user_service.download_profile_photo(
        user_id, current_member.organization_id, db
    )


@router.get(
    "/{user_id}",
    response_model=OrganizationMemberResponse,
    summary="Consulta dados de um usuário da mesma organização",
    description=(
        "Retorna os dados cadastrais e papel do usuário especificado, restrito aos membros "
        "da mesma organização do solicitante. Membros desativados permanecem consultáveis "
        "para fins de histórico e auditoria da instituição."
    ),
)
async def get_user_by_id(
    user_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMemberResponse:
    member = await user_service.get_user_in_org(
        user_id=user_id,
        organization_id=current_member.organization_id,
        db=db,
    )
    photos = await storage_service.get_profile_photo_fields(
        current_member.organization_id, {member.user_id: member.user.profile_photo_path}
    )

    return OrganizationMemberResponse(
        **photos[member.user_id].model_dump(),
        organization_id=member.organization_id,
        user_id=member.user.id,
        email=member.user.email,
        full_name=member.user.full_name,
        role=member.role,
        is_active=member.is_active,
        joined_at=member.joined_at,
    )
