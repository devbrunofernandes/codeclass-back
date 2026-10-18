import logging
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.compensating_transaction import CompensatingTransaction
from app.core.exceptions import AppException, NotFoundException
from app.infrastructure.auth import auth_service
from app.models.organization import OrganizationMember
from app.models.user import User
from app.schemas.user import ProfilePhotoResponse
from app.services.storage_service import USER_PHOTOS_BUCKET, storage_service

logger = logging.getLogger(__name__)


class UserService:
    async def upload_profile_photo(
        self, user_id: UUID, organization_id: UUID, file: UploadFile, db: AsyncSession
    ) -> str:
        statement = (
            select(User)
            .join(OrganizationMember)
            .where(
                User.id == user_id,
                OrganizationMember.organization_id == organization_id,
            )
            .with_for_update(of=User)
            .execution_options(populate_existing=True)
        )
        result = await db.execute(
            statement.where(OrganizationMember.is_active.is_(True))
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise NotFoundException("Usuário não encontrado na organização.")
        previous_path = user.profile_photo_path
        path = await storage_service.upload_profile_photo(
            organization_id, user_id, file
        )
        try:
            user.profile_photo_path = path
            await db.commit()
        except Exception as exc:
            await db.rollback()
            if previous_path is None:
                # Reacquire the lock after rollback: another upload may have
                # committed this deterministic path while the lock was released.
                try:
                    current = (await db.execute(statement)).scalar_one_or_none()
                    if current is None or current.profile_photo_path is None:
                        await storage_service.provider.delete_file(
                            bucket=USER_PHOTOS_BUCKET, path=path
                        )
                finally:
                    await db.rollback()
            raise AppException("Erro ao persistir foto de perfil.", 500) from exc
        return path

    async def download_profile_photo(
        self, user_id: UUID, organization_id: UUID, db: AsyncSession
    ) -> ProfilePhotoResponse:
        member = await self.get_user_in_org(user_id, organization_id, db)
        path = member.user.profile_photo_path
        if path is None:
            raise NotFoundException("Usuário não possui foto de perfil.")
        if path != f"{organization_id}/{user_id}/profile.jpg":
            raise NotFoundException("Foto não encontrada na organização.")
        return await storage_service.get_profile_photo_download(path)

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
            async with CompensatingTransaction(db=db) as tx:
                tx.register(
                    auth_service.update_auth_user,
                    user_id=user_id,
                    full_name=old_full_name,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
        except AppException:
            raise
        except Exception as e:
            raise AppException(
                message=f"Erro ao atualizar usuário no banco de dados: {e!s}",
                status_code=500,
            ) from e

        return user

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
