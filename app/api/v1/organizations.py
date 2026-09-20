from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_member,
    get_db,
    require_admin_or_owner,
    require_owner,
    require_teacher_admin_or_owner,
    verify_org_access,
)
from app.api.v1 import members
from app.models.organization import OrganizationMember
from app.schemas.classroom import ClassroomCreateRequest, ClassroomResponse
from app.schemas.organization import (
    ClassroomSummaryResponse,
    OrganizationRegisterRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    TransferOwnershipRequest,
)
from app.services.classroom_service import classroom_service
from app.services.organization_service import organization_service

router = APIRouter()

# Monta sub-rotas especializadas de membros (/orgs/{org_id}/members/...)
router.include_router(members.router)


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastro público da organização com responsável inicial (Owner)",
)
async def register_organization(
    request: OrganizationRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationResponse:
    return await organization_service.register_organization(request=request, db=db)


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Consulta dados cadastrais da organização",
)
async def get_organization(
    org_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(get_current_active_member)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationResponse:
    await verify_org_access(org_id, current_member)
    return await organization_service.get_organization(org_id=org_id, db=db)


@router.patch(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Atualiza dados cadastrais da organização (Apenas Owner)",
)
async def update_organization(
    org_id: UUID,
    request: OrganizationUpdateRequest,
    current_member: Annotated[OrganizationMember, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationResponse:
    await verify_org_access(org_id, current_member)
    return await organization_service.update_organization(
        org_id=org_id, request=request, db=db
    )


@router.delete(
    "/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Exclui definitivamente a organização (Apenas Owner)",
)
async def delete_organization(
    org_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await verify_org_access(org_id, current_member)
    await organization_service.delete_organization(org_id=org_id, db=db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{org_id}/owner",
    response_model=OrganizationResponse,
    summary="Transfere a titularidade da instituição para outro membro (Apenas Owner)",
)
async def transfer_ownership(
    org_id: UUID,
    request: TransferOwnershipRequest,
    current_member: Annotated[OrganizationMember, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OrganizationResponse:
    await verify_org_access(org_id, current_member)
    return await organization_service.transfer_ownership(
        org_id=org_id,
        request=request,
        current_member=current_member,
        db=db,
    )


@router.get(
    "/{org_id}/classrooms",
    response_model=list[ClassroomSummaryResponse],
    summary="Lista todas as turmas da instituição para auditoria e supervisão (Admin, Owner)",
)
async def list_organization_classrooms(
    org_id: UUID,
    current_member: Annotated[OrganizationMember, Depends(require_admin_or_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ClassroomSummaryResponse]:
    await verify_org_access(org_id, current_member)
    classrooms = await classroom_service.list_organization_classrooms(
        organization_id=org_id, db=db
    )
    return [ClassroomSummaryResponse.model_validate(c) for c in classrooms]


@router.post(
    "/{org_id}/classrooms",
    response_model=ClassroomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cria sala de aula (Teacher assume docência; Admin/Owner indicam docente)",
)
async def create_organization_classroom(
    org_id: UUID,
    request: ClassroomCreateRequest,
    current_member: Annotated[
        OrganizationMember, Depends(require_teacher_admin_or_owner)
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClassroomResponse:
    await verify_org_access(org_id, current_member)
    classroom = await classroom_service.create_classroom(
        organization_id=org_id,
        name=request.name,
        description=request.description,
        teacher_id=request.teacher_id,
        creator_member=current_member,
        db=db,
    )
    return ClassroomResponse.model_validate(classroom)
