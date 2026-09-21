import logging
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    AppException,
    AuthError,
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.models.enums import OrgRole
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.organization import (
    MemberRoleUpdateRequest,
    MemberStatusUpdateRequest,
    OrganizationMemberCreate,
    OrganizationMemberResponse,
)
from app.services.auth_service import auth_service

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
            raise BadRequestException(
                "Não é permitido criar um membro diretamente com papel de proprietário."
            )

        # Regra RBAC: Apenas o Owner pode cadastrar Administradores (HLD matriz RBAC)
        if request.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise ForbiddenException(
                "Apenas o proprietário (Owner) pode cadastrar novos administradores."
            )

        # Verifica se e-mail já existe
        email_res = await db.execute(select(User).where(User.email == request.email))
        if email_res.scalar_one_or_none() is not None:
            raise ConflictException("Já existe um usuário com este e-mail cadastrado.")

        # 1. Cria usuário no provedor de autenticação (AuthError sobe como AppException)
        auth_user = await auth_service.create_auth_user(
            email=request.email,
            password=request.password,
            full_name=request.full_name,
        )

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
            )
            db.add(new_member)
            await db.commit()
            await db.refresh(new_member)
        except IntegrityError as e:
            await db.rollback()
            # Rollback compensatório no Supabase Auth
            try:
                await auth_service.delete_auth_user(user_id)
            except AuthError as cleanup_err:
                logger.warning(
                    "Falha ao reverter usuário %s no auth provider: %s",
                    user_id,
                    cleanup_err,
                )
            raise ConflictException(
                "Conflito ao registrar membro na organização."
            ) from e
        except Exception as e:
            await db.rollback()
            try:
                await auth_service.delete_auth_user(user_id)
            except AuthError as cleanup_err:
                logger.warning(
                    "Falha ao reverter usuário %s no auth provider: %s",
                    user_id,
                    cleanup_err,
                )
            raise AppException(
                message=f"Erro interno ao criar membro: {e!s}",
                status_code=500,
            ) from e

        return OrganizationMemberResponse(
            organization_id=new_member.organization_id,
            user_id=new_user.id,
            email=new_user.email,
            full_name=new_user.full_name,
            role=new_member.role,
            is_active=new_member.is_active,
            joined_at=new_member.joined_at,
        )

    async def list_members(
        self,
        org_id: UUID,
        role: OrgRole | None,
        is_active: bool | None,
        search: str | None,
        offset: int,
        limit: int,
        db: AsyncSession,
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
            search_pattern = f"%{search}%"
            stmt = stmt.join(OrganizationMember.user).where(
                or_(
                    User.full_name.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                )
            )

        stmt = stmt.offset(offset).limit(limit)
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
            raise BadRequestException(
                "Para transferir a posse da organização, utilize o endpoint de transferência de titularidade."
            )

        # RBAC: apenas o Owner pode alterar papéis para/de Admin
        if request.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise ForbiddenException(
                "Apenas o proprietário (Owner) pode promover membros para administrador."
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
            raise NotFoundException("Membro não encontrado nesta organização.")

        if target_member.role == OrgRole.OWNER:
            raise BadRequestException(
                "O papel do proprietário não pode ser modificado por esta rota."
            )

        if target_member.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise ForbiddenException(
                "Apenas o proprietário (Owner) pode rebaixar administradores."
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
            raise BadRequestException(
                "Não é permitido alterar o próprio status de ativação."
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
            raise NotFoundException("Membro não encontrado nesta organização.")

        if target_member.role == OrgRole.OWNER:
            raise BadRequestException(
                "Não é permitido desativar o proprietário da organização."
            )

        # Admin não pode desativar outro admin nem o owner
        if target_member.role == OrgRole.ADMIN and current_member.role != OrgRole.OWNER:
            raise ForbiddenException(
                "Apenas o proprietário pode desativar administradores."
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
