import asyncio
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.compensating_transaction import CompensatingTransaction
from app.core.exceptions import (
    AppException,
    AuthError,
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.infrastructure.auth import auth_service
from app.models.enums import OrgRole
from app.models.organization import Organization, OrganizationMember
from app.models.user import User
from app.schemas.organization import (
    OrganizationRegisterRequest,
    OrganizationResponse,
    OrganizationUpdateRequest,
    TransferOwnershipRequest,
)

logger = logging.getLogger(__name__)


class OrganizationService:
    async def register_organization(
        self,
        request: OrganizationRegisterRequest,
        db: AsyncSession,
    ) -> OrganizationResponse:
        # Verifica duplicidade de slug
        slug_res = await db.execute(
            select(Organization).where(Organization.slug == request.slug)
        )
        if slug_res.scalar_one_or_none() is not None:
            raise ConflictException("Já existe uma organização com este slug.")

        # Verifica duplicidade de email
        email_res = await db.execute(
            select(User).where(User.email == request.owner.email)
        )
        if email_res.scalar_one_or_none() is not None:
            raise ConflictException("Já existe um usuário cadastrado com este e-mail.")

        # 1. Cria usuário no provedor de autenticação (AuthError sobe como AppException)
        auth_user = await auth_service.create_auth_user(
            email=request.owner.email,
            password=request.owner.password,
            full_name=request.owner.full_name,
        )

        user_id = auth_user["id"]

        try:
            async with CompensatingTransaction(db=db) as tx:
                tx.register(auth_service.delete_auth_user, user_id)

                # 2. Persiste usuário local
                owner_user = User(
                    id=user_id,
                    email=request.owner.email,
                    full_name=request.owner.full_name,
                )
                db.add(owner_user)
                await db.flush()

                # 3. Cria organização
                organization = Organization(
                    name=request.name,
                    slug=request.slug,
                    owner_id=owner_user.id,
                )
                db.add(organization)
                await db.flush()

                # 4. Cria vínculo como Owner
                member = OrganizationMember(
                    organization_id=organization.id,
                    user_id=owner_user.id,
                    role=OrgRole.OWNER,
                    is_active=True,
                )
                db.add(member)

                await db.commit()
                await db.refresh(organization)
        except IntegrityError as e:
            raise ConflictException(
                "Organização com este slug ou usuário com este e-mail já existe."
            ) from e
        except AppException:
            raise
        except Exception as e:
            raise AppException(
                message=f"Erro ao cadastrar organização: {e!s}",
                status_code=500,
            ) from e

        return OrganizationResponse.model_validate(organization)

    async def get_organization(
        self,
        org_id: UUID,
        db: AsyncSession,
    ) -> OrganizationResponse:
        res = await db.execute(select(Organization).where(Organization.id == org_id))
        org = res.scalar_one_or_none()
        if org is None:
            raise NotFoundException("Organização não encontrada.")
        return OrganizationResponse.model_validate(org)

    async def update_organization(
        self,
        org_id: UUID,
        request: OrganizationUpdateRequest,
        db: AsyncSession,
    ) -> OrganizationResponse:
        res = await db.execute(select(Organization).where(Organization.id == org_id))
        org = res.scalar_one_or_none()
        if org is None:
            raise NotFoundException("Organização não encontrada.")

        if request.slug is not None and request.slug != org.slug:
            slug_check = await db.execute(
                select(Organization).where(
                    Organization.slug == request.slug, Organization.id != org_id
                )
            )
            if slug_check.scalar_one_or_none() is not None:
                raise ConflictException(
                    "Este slug já está em uso por outra organização."
                )
            org.slug = request.slug

        if request.name is not None:
            org.name = request.name

        try:
            await db.commit()
            await db.refresh(org)
        except IntegrityError as e:
            await db.rollback()
            raise ConflictException(
                "Este slug já está em uso por outra organização."
            ) from e

        return OrganizationResponse.model_validate(org)

    async def delete_organization(
        self,
        org_id: UUID,
        db: AsyncSession,
    ) -> None:
        res = await db.execute(select(Organization).where(Organization.id == org_id))
        org = res.scalar_one_or_none()
        if org is None:
            raise NotFoundException("Organização não encontrada.")

        # 1. Coleta os user_id de todos os membros da organização (incluindo o owner)
        members_res = await db.execute(
            select(OrganizationMember.user_id).where(
                OrganizationMember.organization_id == org_id
            )
        )
        user_ids = members_res.scalars().all()

        # 2. Deleta a organização (cascateia para salas, assignments, submissions, messages e organization_members)
        await db.delete(org)
        await db.flush()

        # 3. Deleta os usuários da organização (o trigger no PostgreSQL remove de auth.users automaticamente)
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))

        await db.commit()

        # 4. Fallback defensivo para garantir limpeza no provedor de autenticação
        if user_ids:

            async def _safe_delete(uid: UUID) -> None:
                try:
                    await auth_service.delete_auth_user(uid)
                except AuthError:
                    pass  # Já removido pelo trigger de banco

            await asyncio.gather(
                *[_safe_delete(uid) for uid in user_ids], return_exceptions=True
            )

    async def transfer_ownership(
        self,
        org_id: UUID,
        request: TransferOwnershipRequest,
        current_member: OrganizationMember,
        db: AsyncSession,
    ) -> OrganizationResponse:
        if request.new_owner_id == current_member.user_id:
            raise BadRequestException(
                "O usuário indicado já é o proprietário da organização."
            )

        # Verifica se o novo proprietário é membro ativo da organização
        stmt = select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == request.new_owner_id,
        )
        res = await db.execute(stmt)
        new_owner_member = res.scalar_one_or_none()

        if new_owner_member is None:
            raise NotFoundException(
                "O novo proprietário deve ser um membro vinculado a esta organização."
            )

        if not new_owner_member.is_active:
            raise BadRequestException(
                "Não é possível transferir a posse para um membro desativado."
            )

        # Busca organização
        org_res = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        organization = org_res.scalar_one_or_none()
        if organization is None:
            raise NotFoundException("Organização não encontrada.")

        # Transfere posse:
        # 1. Atualiza antigo owner para admin (HLD linha 85)
        current_member.role = OrgRole.ADMIN
        # 2. Atualiza novo owner para owner
        new_owner_member.role = OrgRole.OWNER
        # 3. Atualiza owner_id na organização
        organization.owner_id = request.new_owner_id

        await db.commit()
        await db.refresh(organization)

        return OrganizationResponse.model_validate(organization)


organization_service = OrganizationService()
