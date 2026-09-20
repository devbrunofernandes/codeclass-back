import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.organization import (
    MemberRoleUpdateRequest,
    MemberStatusUpdateRequest,
    OrganizationMemberCreate,
    OrganizationMemberResponse,
)
from app.services.auth_service import AuthError, auth_service

logger = logging.getLogger(__name__)


class MemberService:
    async def add_member(
        self,
        org_id: UUID,
        request: OrganizationMemberCreate,
        current_member: OrganizationMember,
        db: AsyncSession,
    ) -> OrganizationMemberResponse:
        # Não permite criar outro Owner diretamente
        if request.role == OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é permitido criar um membro diretamente com papel de proprietário.",
            )

        # Regra RBAC: Apenas o Owner pode cadastrar Administradores (HLD matriz RBAC)
        if request.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o proprietário (Owner) pode cadastrar novos administradores.",
            )

        # Verifica se e-mail já existe
        email_res = await db.execute(select(User).where(User.email == request.email))
        if email_res.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um usuário com este e-mail cadastrado.",
            )

        # 1. Cria usuário no provedor de autenticação
        try:
            auth_user = await auth_service.create_auth_user(
                email=request.email,
                password=request.password,
                full_name=request.full_name,
            )
        except AuthError as e:
            raise HTTPException(status_code=e.status_code, detail=e.message) from e

        user_id = auth_user["id"]

        try:
            # 2. Persiste usuário no banco local
            new_user = User(
                id=user_id,
                email=request.email,
                full_name=request.full_name,
            )
            db.add(new_user)
            await db.flush()

            # 3. Cria vínculo na organização
            new_member = OrganizationMember(
                organization_id=org_id,
                user_id=new_user.id,
                role=request.role,
                is_active=True,
            )
            db.add(new_member)
            await db.commit()
            await db.refresh(new_member)

            return OrganizationMemberResponse(
                organization_id=new_member.organization_id,
                user_id=new_user.id,
                email=new_user.email,
                full_name=new_user.full_name,
                role=new_member.role,
                is_active=new_member.is_active,
                joined_at=new_member.joined_at,
            )
        except IntegrityError as e:
            await db.rollback()
            try:
                await auth_service.delete_auth_user(user_id)
            except AuthError as cleanup_err:
                logger.warning(
                    "Falha ao remover usuário do provedor no rollback de membro: %s",
                    cleanup_err,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Membro com este e-mail já cadastrado.",
            ) from e
        except Exception as e:
            await db.rollback()
            try:
                await auth_service.delete_auth_user(user_id)
            except AuthError as cleanup_err:
                logger.warning(
                    "Falha ao remover usuário do provedor no rollback de membro: %s",
                    cleanup_err,
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao cadastrar membro: {e!s}",
            ) from e

    async def list_members(
        self,
        org_id: UUID,
        db: AsyncSession,
        role: OrgRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrganizationMemberResponse]:
        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(OrganizationMember.organization_id == org_id)
        )

        if role is not None:
            stmt = stmt.where(OrganizationMember.role == role)
        if is_active is not None:
            stmt = stmt.where(OrganizationMember.is_active == is_active)
        if search:
            search_filter = f"%{search.lower()}%"
            stmt = stmt.join(OrganizationMember.user).where(
                or_(
                    func.lower(User.full_name).like(search_filter),
                    func.lower(User.email).like(search_filter),
                )
            )

        stmt = (
            stmt.order_by(OrganizationMember.joined_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        members = result.scalars().all()

        return [
            OrganizationMemberResponse(
                organization_id=m.organization_id,
                user_id=m.user.id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=m.role,
                is_active=m.is_active,
                joined_at=m.joined_at,
            )
            for m in members
        ]

    async def update_member_role(
        self,
        org_id: UUID,
        user_id: UUID,
        request: MemberRoleUpdateRequest,
        current_member: OrganizationMember,
        db: AsyncSession,
    ) -> OrganizationMemberResponse:
        if request.role == OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Para transferir a posse da organização, utilize o endpoint de transferência de titularidade.",
            )

        # RBAC: apenas o Owner pode alterar papéis para/de Admin
        if request.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o proprietário (Owner) pode promover membros para administrador.",
            )

        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        result = await db.execute(stmt)
        target_member = result.scalar_one_or_none()

        if target_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membro não encontrado nesta organização.",
            )

        if target_member.role == OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O papel do proprietário não pode ser modificado por esta rota.",
            )

        if target_member.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o proprietário (Owner) pode rebaixar administradores.",
            )

        target_member.role = request.role
        await db.commit()
        await db.refresh(target_member)

        return OrganizationMemberResponse(
            organization_id=target_member.organization_id,
            user_id=target_member.user.id,
            email=target_member.user.email,
            full_name=target_member.user.full_name,
            role=target_member.role,
            is_active=target_member.is_active,
            joined_at=target_member.joined_at,
        )

    async def update_member_status(
        self,
        org_id: UUID,
        user_id: UUID,
        request: MemberStatusUpdateRequest,
        current_member: OrganizationMember,
        db: AsyncSession,
    ) -> OrganizationMemberResponse:
        if current_member.user_id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é permitido alterar o próprio status de ativação.",
            )

        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        result = await db.execute(stmt)
        target_member = result.scalar_one_or_none()

        if target_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Membro não encontrado nesta organização.",
            )

        if target_member.role == OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é permitido desativar o proprietário da organização.",
            )

        # Admin não pode desativar outro admin nem o owner
        if target_member.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas o proprietário pode desativar administradores.",
            )

        target_member.is_active = request.is_active
        await db.commit()
        await db.refresh(target_member)

        return OrganizationMemberResponse(
            organization_id=target_member.organization_id,
            user_id=target_member.user.id,
            email=target_member.user.email,
            full_name=target_member.user.full_name,
            role=target_member.role,
            is_active=target_member.is_active,
            joined_at=target_member.joined_at,
        )


member_service = MemberService()
