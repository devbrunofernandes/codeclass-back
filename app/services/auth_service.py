from typing import Any, cast
from uuid import UUID

import anyio
from jose import JWTError, jwt
from supabase_auth.types import AdminUserAttributes

from app.core.config import settings
from supabase import Client, ClientOptions, create_client


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthService:
    def __init__(self) -> None:
        self._admin_client: Client | None = None

    def _create_raw_client(self) -> Client:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise AuthError(
                "Configurações do provedor de autenticação ausentes.", status_code=500
            )
        return create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY,
            options=ClientOptions(
                persist_session=False,
                auto_refresh_token=False,
            ),
        )

    @property
    def admin_client(self) -> Client:
        if self._admin_client is None:
            self._admin_client = self._create_raw_client()
        return self._admin_client

    async def create_auth_user(
        self, email: str, password: str, full_name: str
    ) -> dict[str, Any]:
        """Cria um usuário no provedor de autenticação com credenciais administrativas."""
        try:
            res = await anyio.to_thread.run_sync(
                lambda: self.admin_client.auth.admin.create_user(
                    {
                        "email": email,
                        "password": password,
                        "user_metadata": {"full_name": full_name},
                        "email_confirm": True,
                    }
                )
            )
            if not res or not res.user:
                raise AuthError("Falha ao registrar usuário no provedor de autenticação.")
            return {
                "id": UUID(res.user.id),
                "email": res.user.email,
                "full_name": full_name,
            }
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Erro no provedor de autenticação: {e!s}") from e

    async def sign_in_with_password(
        self, email: str, password: str
    ) -> dict[str, Any]:
        """Autentica o usuário com email e senha usando um cliente efêmero sem contaminar o admin."""
        try:
            auth_client = self._create_raw_client()
            res = await anyio.to_thread.run_sync(
                lambda: auth_client.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
            )
            if not res or not res.session or not res.user:
                raise AuthError("Credenciais inválidas.", status_code=401)
            return {
                "access_token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "user_id": UUID(res.user.id),
                "email": res.user.email,
                "full_name": (res.user.user_metadata or {}).get("full_name", ""),
            }
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError("Credenciais inválidas.", status_code=401) from e

    async def refresh_session(self, refresh_token: str) -> dict[str, Any]:
        """Renova a sessão a partir do refresh token usando cliente efêmero isolado."""
        try:
            auth_client = self._create_raw_client()
            res = await anyio.to_thread.run_sync(
                lambda: auth_client.auth.refresh_session(refresh_token)
            )
            if not res or not res.session or not res.user:
                raise AuthError("Token de atualização inválido ou expirado.", status_code=401)
            return {
                "access_token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
                "user_id": UUID(res.user.id),
                "email": res.user.email,
            }
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError("Falha ao renovar sessão.", status_code=401) from e

    async def delete_auth_user(self, user_id: UUID | str) -> None:
        """Remove o usuário do provedor de autenticação com privilégio administrativo."""
        try:
            await anyio.to_thread.run_sync(
                lambda: self.admin_client.auth.admin.delete_user(str(user_id))
            )
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Erro ao remover usuário do provedor: {e!s}") from e

    async def verify_jwt_token(self, token: str) -> dict[str, Any]:
        """Valida e decodifica o JWT localmente (HS256) ou via Supabase Auth (ES256/JWKS)."""
        alg: str | None = None
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg")
        except JWTError:
            alg = None

        if alg == "HS256" and settings.SUPABASE_JWT_SECRET:
            try:
                payload = jwt.decode(
                    token,
                    settings.SUPABASE_JWT_SECRET,
                    algorithms=["HS256"],
                    options={"verify_aud": False},
                )
                sub = payload.get("sub")
                if not sub:
                    raise AuthError("Token inválido: ausência de 'sub'.", status_code=401)
                return cast(dict[str, Any], payload)
            except JWTError as e:
                raise AuthError(f"Token inválido ou expirado: {e!s}", status_code=401) from e

        # Fallback seguro para validação no Supabase Auth usando cliente efêmero isolado
        try:
            auth_client = self._create_raw_client()
            user_res = await anyio.to_thread.run_sync(
                lambda: auth_client.auth.get_user(jwt=token)
            )
            if not user_res or not user_res.user:
                raise AuthError("Token inválido ou sessão expirada.", status_code=401)
            return {
                "sub": user_res.user.id,
                "email": user_res.user.email,
                "user_metadata": user_res.user.user_metadata or {},
            }
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError("Token inválido ou expirado.", status_code=401) from e

    async def update_auth_user(
        self,
        user_id: UUID | str,
        *,
        full_name: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Atualiza metadados ou credenciais do usuário no provedor de autenticação."""
        attributes: AdminUserAttributes = {}
        if password is not None:
            attributes["password"] = password
        if full_name is not None:
            attributes["user_metadata"] = {"full_name": full_name}

        if not attributes:
            return {"id": str(user_id)}

        try:
            res = await anyio.to_thread.run_sync(
                lambda: self.admin_client.auth.admin.update_user_by_id(
                    str(user_id),
                    attributes,
                )
            )
            if not res or not res.user:
                raise AuthError("Falha ao atualizar usuário no provedor de autenticação.")
            return {
                "id": UUID(res.user.id),
                "email": res.user.email,
                "full_name": (res.user.user_metadata or {}).get("full_name", full_name),
            }
        except Exception as e:
            if isinstance(e, AuthError):
                raise
            raise AuthError(f"Erro ao atualizar usuário no provedor: {e!s}") from e


auth_service = AuthService()
