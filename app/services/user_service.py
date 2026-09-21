import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, AuthError, NotFoundException
from app.models.organization import OrganizationMember
from app.models.user import User
from app.services.auth_service import auth_service

logger = logging.getLogger(__name__)


class UserService:
    async def update_profile(
        self,
        user: User,
        full_name: str,
        db: AsyncSession,
    ) -> User:
        user_id = user.id
        old_full_name = user.full_name

        await auth_service.update_auth_user(
            user_id=user_id,
            full_name=full_name,
        )

        user.full_name = full_name
        try:
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user
        except Exception as e:
            await db.rollback()
            # Rollback compensatório no Supabase Auth para restaurar o nome anterior
            try:
                await auth_service.update_auth_user(
                    user_id=user_id,
                    full_name=old_full_name,
                )
            except AuthError as cleanup_err:
                logger.warning(
                    "Falha ao reverter metadados no auth provider no rollback de usuário %s: %s",
                    user_id,
                    cleanup_err,
                )
            raise AppException(
                message=f"Erro ao atualizar usuário no banco de dados: {e!s}",
                status_code=500,
            ) from e

    async def change_password(
        self,
        user_id: UUID,
        password: str,
    ) -> None:
        await auth_service.update_auth_user(
            user_id=user_id,
            password=password,
        )

    async def get_user_in_org(
        self,
        user_id: UUID,
        organization_id: UUID,
        db: AsyncSession,
    ) -> OrganizationMember:
        stmt = (
            select(OrganizationMember)
            .options(selectinload(OrganizationMember.user))
            .where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        member = result.scalar_one_or_none()

        if member is None or member.user is None:
            raise NotFoundException("Usuário não encontrado na organização.")

        return member


user_service = UserService()
