import contextlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import AuthError, auth_service
from tests.integration.conftest import OrgContext


@pytest.mark.asyncio
async def test_delete_organization_cleans_up_auth_users_table(
    async_client: AsyncClient,
    registered_org: OrgContext,
    db_session: AsyncSession,
) -> None:
    """Valida que a deleção de uma organização limpa os usuários de public.users e de auth.users."""
    owner_uuid = uuid.UUID(registered_org.owner_id)
    org_uuid = uuid.UUID(registered_org.org_id)

    # 1. Cadastra um membro adicional (Professor) com usuário real no GoTrue
    uid_suffix = uuid.uuid4().hex[:6]
    teacher_email = f"teacher_del_{uid_suffix}@codeclass-int.com"
    teacher_password = "senhaSegura123!"
    teacher_name = f"Professor Cleanup {uid_suffix}"

    teacher_res = await async_client.post(
        f"/api/v1/orgs/{registered_org.org_id}/members",
        headers=registered_org.auth_headers,
        json={
            "email": teacher_email,
            "full_name": teacher_name,
            "password": teacher_password,
            "role": "teacher",
        },
    )
    assert teacher_res.status_code == 201
    teacher_data = teacher_res.json()
    teacher_id = teacher_data["user_id"]
    teacher_uuid = uuid.UUID(teacher_id)
    registered_org.track_user(teacher_id)

    # 2. Confirma que ambos os usuários existem na tabela real auth.users do Supabase
    owner_auth_pre = (
        await db_session.execute(
            text("SELECT id FROM auth.users WHERE id = :id"),
            {"id": owner_uuid},
        )
    ).scalar_one_or_none()
    assert owner_auth_pre is not None, "Owner deve existir na tabela auth.users antes da deleção"

    teacher_auth_pre = (
        await db_session.execute(
            text("SELECT id FROM auth.users WHERE id = :id"),
            {"id": teacher_uuid},
        )
    ).scalar_one_or_none()
    assert teacher_auth_pre is not None, "Professor deve existir na tabela auth.users antes da deleção"

    # Confirma existência em public.users
    assert await db_session.get(User, owner_uuid) is not None
    assert await db_session.get(User, teacher_uuid) is not None

    # 3. Executa a deleção da organização via API
    del_res = await async_client.delete(
        f"/api/v1/orgs/{registered_org.org_id}",
        headers=registered_org.auth_headers,
    )
    assert del_res.status_code == 204

    # Expira o cache da sessão para garantir leitura fresca do banco
    db_session.expire_all()

    # 4. Validação direta no banco: tabela auth.users NÃO deve mais conter os usuários
    owner_auth_post = (
        await db_session.execute(
            text("SELECT id FROM auth.users WHERE id = :id"),
            {"id": owner_uuid},
        )
    ).scalar_one_or_none()
    assert owner_auth_post is None, "Owner deve ser removido de auth.users após deleção da organização"

    teacher_auth_post = (
        await db_session.execute(
            text("SELECT id FROM auth.users WHERE id = :id"),
            {"id": teacher_uuid},
        )
    ).scalar_one_or_none()
    assert teacher_auth_post is None, "Professor deve ser removido de auth.users após deleção da organização"

    # 5. Validação direta no banco: tabelas públicas
    assert await db_session.get(Organization, org_uuid) is None
    assert await db_session.get(User, owner_uuid) is None
    assert await db_session.get(User, teacher_uuid) is None

    # 6. Validação via GoTrue: tentativa de login com credenciais excluídas deve falhar
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={
            "email": registered_org.owner_email,
            "password": registered_org.owner_password,
        },
    )
    assert login_res.status_code == 401


@pytest.mark.asyncio
async def test_postgres_trigger_deletes_from_auth_users_on_public_user_delete(
    db_session: AsyncSession,
) -> None:
    """Valida isoladamente que o trigger trigger_on_public_user_deleted no PostgreSQL
    remove o registro correspondente em auth.users quando um registro é deletado de public.users."""
    uid = uuid.uuid4()
    email = f"trigger_test_{uid.hex[:8]}@codeclass-int.com"

    # 1. Cria usuário real no Supabase Auth
    auth_data = await auth_service.create_auth_user(
        email=email,
        password="password123!",
        full_name="Trigger Test User",
    )
    user_uuid = uuid.UUID(str(auth_data["id"]))

    try:
        # 2. Insere usuário em public.users
        user = User(
            id=user_uuid,
            email=email,
            full_name="Trigger Test User",
        )
        db_session.add(user)
        await db_session.commit()

        # Confirma presença em auth.users
        auth_pre = (
            await db_session.execute(
                text("SELECT id FROM auth.users WHERE id = :id"),
                {"id": user_uuid},
            )
        ).scalar_one_or_none()
        assert auth_pre is not None

        # 3. Deleta de public.users diretamente no banco
        await db_session.delete(user)
        await db_session.commit()

        # 4. Confirma que o trigger disparou e removeu de auth.users
        auth_post = (
            await db_session.execute(
                text("SELECT id FROM auth.users WHERE id = :id"),
                {"id": user_uuid},
            )
        ).scalar_one_or_none()
        assert auth_post is None, "Trigger deve remover o usuário correspondente de auth.users"

    finally:
        # Limpeza defensiva caso o teste falhe antes do delete
        with contextlib.suppress(AuthError):
            await auth_service.delete_auth_user(user_uuid)
