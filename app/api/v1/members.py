from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_member,
    get_db,
    require_admin_or_owner,
    require_org_member,
)
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.schemas.organization import (
    MemberRoleUpdateRequest,
    MemberStatusUpdateRequest,
    OrganizationMemberCreate,
    OrganizationMemberResponse,
)
from app.services.member_service import member_service

router = APIRouter(dependencies=[Depends(require_org_member)])


@router.post(
    "/{org_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastra novo membro institucional na organização",
)
async def add_member(
    org_id: UUID,
    request: OrganizationMemberCreate,
    current_member: Annotated[OrganizationMember, Depends(require_admin_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMemberResponse:
    return await member_service.add_member(
        org_id=org_id,
        request=request,
        current_member=current_member,
        db=db,
    )


@router.get(
    "/{org_id}/members",
    response_model=list[OrganizationMemberResponse],
    summary="Lista todos os membros vinculados à instituição",
)
async def list_members(
    org_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
    role: OrgRole | None = None,
    is_active: bool | None = None,
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[OrganizationMemberResponse]:
    return await member_service.list_members(
        org_id=org_id,
        db=db,
        role=role,
        is_active=is_active,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.put(
    "/{org_id}/members/{user_id}/role",
    response_model=OrganizationMemberResponse,
    summary="Atualiza o papel institucional do membro",
)
async def update_member_role(
    org_id: UUID,
    user_id: UUID,
    request: MemberRoleUpdateRequest,
    current_member: Annotated[OrganizationMember, Depends(require_admin_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMemberResponse:
    return await member_service.update_member_role(
        org_id=org_id,
        user_id=user_id,
        request=request,
        current_member=current_member,
        db=db,
    )


@router.patch(
    "/{org_id}/members/{user_id}/status",
    response_model=OrganizationMemberResponse,
    summary="Ativa ou desativa o acesso do membro na organização",
)
async def update_member_status(
    org_id: UUID,
    user_id: UUID,
    request: MemberStatusUpdateRequest,
    current_member: Annotated[OrganizationMember, Depends(require_admin_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationMemberResponse:
    return await member_service.update_member_status(
        org_id=org_id,
        user_id=user_id,
        request=request,
        current_member=current_member,
        db=db,
    )
