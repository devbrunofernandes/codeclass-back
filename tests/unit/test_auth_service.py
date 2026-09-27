import uuid
from unittest.mock import MagicMock

import pytest
from jose import jwt

from app.core.config import settings
from app.core.exceptions import AuthError
from app.services.auth_service import AuthService


@pytest.fixture
def auth_svc() -> AuthService:
    return AuthService()


# --- _create_raw_client & admin_client ---


def test_create_raw_client_missing_config_raises_500(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "")

    with pytest.raises(
        AuthError, match="Configurações do provedor de autenticação ausentes."
    ) as exc_info:
        auth_svc._create_raw_client()
    assert exc_info.value.status_code == 500


def test_create_raw_client_success(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_KEY", "example-anon-key")
    mock_create = MagicMock()
    monkeypatch.setattr("app.services.auth_service.create_client", mock_create)

    client = auth_svc._create_raw_client()
    assert client is mock_create.return_value
    mock_create.assert_called_once()


def test_admin_client_singleton_behavior(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_client = MagicMock()
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_client)

    client1 = auth_svc.admin_client
    client2 = auth_svc.admin_client

    assert client1 is mock_client
    assert client2 is mock_client


# --- create_auth_user ---


@pytest.mark.asyncio
async def test_create_auth_user_success(auth_svc: AuthService) -> None:
    mock_admin_client = MagicMock()
    user_id = uuid.uuid4()
    mock_user = MagicMock(id=str(user_id), email="test@example.com")
    mock_admin_client.auth.admin.create_user.return_value = MagicMock(user=mock_user)
    auth_svc._admin_client = mock_admin_client

    result = await auth_svc.create_auth_user("test@example.com", "pass123", "Full Name")

    assert result["id"] == user_id
    assert result["email"] == "test@example.com"
    assert result["full_name"] == "Full Name"


@pytest.mark.asyncio
async def test_create_auth_user_when_response_is_empty_raises_autherror(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.create_user.return_value = None
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(
        AuthError, match="Falha ao registrar usuário no provedor de autenticação."
    ):
        await auth_svc.create_auth_user("test@example.com", "pass123", "Full Name")


@pytest.mark.asyncio
async def test_create_auth_user_when_sdk_raises_exception(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.create_user.side_effect = RuntimeError(
        "Supabase network down"
    )
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(
        AuthError, match="Erro no provedor de autenticação: Supabase network down"
    ):
        await auth_svc.create_auth_user("test@example.com", "pass123", "Full Name")


@pytest.mark.asyncio
async def test_create_auth_user_re_raises_existing_autherror(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.create_user.side_effect = AuthError(
        "Custom auth error", status_code=400
    )
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.create_auth_user("test@example.com", "pass123", "Full Name")
    assert exc_info.value.status_code == 400


# --- sign_in_with_password ---


@pytest.mark.asyncio
async def test_sign_in_with_password_success(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(
        id=str(user_id), email="user@test.com", user_metadata={"full_name": "Test User"}
    )
    mock_session = MagicMock(access_token="acc_token", refresh_token="ref_token")
    mock_auth_client = MagicMock()
    mock_auth_client.auth.sign_in_with_password.return_value = MagicMock(
        session=mock_session, user=mock_user
    )
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    result = await auth_svc.sign_in_with_password("user@test.com", "secret")

    assert result["access_token"] == "acc_token"
    assert result["refresh_token"] == "ref_token"
    assert result["user_id"] == user_id
    assert result["email"] == "user@test.com"
    assert result["full_name"] == "Test User"


@pytest.mark.asyncio
async def test_sign_in_with_password_when_empty_session_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.sign_in_with_password.return_value = MagicMock(
        session=None, user=None
    )
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.sign_in_with_password("user@test.com", "secret")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_sign_in_with_password_when_sdk_exception_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.sign_in_with_password.side_effect = Exception("Invalid login")
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.sign_in_with_password("user@test.com", "secret")
    assert exc_info.value.status_code == 401


# --- refresh_session ---


@pytest.mark.asyncio
async def test_refresh_session_success(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(id=str(user_id), email="refresh@test.com")
    mock_session = MagicMock(access_token="new_acc", refresh_token="new_ref")
    mock_auth_client = MagicMock()
    mock_auth_client.auth.refresh_session.return_value = MagicMock(
        session=mock_session, user=mock_user
    )
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    result = await auth_svc.refresh_session("valid_refresh")

    assert result["access_token"] == "new_acc"
    assert result["refresh_token"] == "new_ref"
    assert result["user_id"] == user_id
    assert result["email"] == "refresh@test.com"


@pytest.mark.asyncio
async def test_refresh_session_when_empty_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.refresh_session.return_value = MagicMock(
        session=None, user=None
    )
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.refresh_session("bad_token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_refresh_session_when_sdk_exception_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.refresh_session.side_effect = Exception(
        "Expired refresh token"
    )
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.refresh_session("expired_token")
    assert exc_info.value.status_code == 401


# --- delete_auth_user ---


@pytest.mark.asyncio
async def test_delete_auth_user_success(auth_svc: AuthService) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.delete_user.return_value = None
    auth_svc._admin_client = mock_admin_client

    user_id = uuid.uuid4()
    await auth_svc.delete_auth_user(user_id)
    mock_admin_client.auth.admin.delete_user.assert_called_once_with(str(user_id))


@pytest.mark.asyncio
async def test_delete_auth_user_when_sdk_raises_exception(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.delete_user.side_effect = Exception("User not found")
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(AuthError, match="Erro ao remover usuário do provedor"):
        await auth_svc.delete_auth_user(uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_auth_user_re_raises_existing_autherror(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.delete_user.side_effect = AuthError(
        "Custom auth error", status_code=400
    )
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(AuthError) as exc_info:
        await auth_svc.delete_auth_user(uuid.uuid4())
    assert exc_info.value.status_code == 400


# --- verify_jwt_token ---


@pytest.mark.asyncio
async def test_verify_jwt_token_hs256_success(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = str(uuid.uuid4())
    monkeypatch.setattr(
        settings, "SUPABASE_JWT_SECRET", "test-secret-at-least-32-chars-long"
    )
    token = jwt.encode(
        {"sub": user_id, "email": "valid@example.com"},
        "test-secret-at-least-32-chars-long",
        algorithm="HS256",
    )

    payload = await auth_svc.verify_jwt_token(token)
    assert payload["sub"] == user_id
    assert payload["email"] == "valid@example.com"


@pytest.mark.asyncio
async def test_verify_jwt_token_missing_sub_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "SUPABASE_JWT_SECRET", "test-secret-at-least-32-chars-long"
    )
    token = jwt.encode(
        {"email": "nosub@example.com"},
        "test-secret-at-least-32-chars-long",
        algorithm="HS256",
    )

    with pytest.raises(
        AuthError, match="Token inválido: ausência de 'sub'."
    ) as exc_info:
        await auth_svc.verify_jwt_token(token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_jwt_token_invalid_signature_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        settings, "SUPABASE_JWT_SECRET", "test-secret-at-least-32-chars-long"
    )
    token = jwt.encode(
        {"sub": str(uuid.uuid4())},
        "different-secret-32-chars-long-1234",
        algorithm="HS256",
    )

    with pytest.raises(AuthError, match="Token inválido ou expirado") as exc_info:
        await auth_svc.verify_jwt_token(token)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_jwt_token_fallback_success(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = str(uuid.uuid4())
    mock_user = MagicMock(
        id=user_id, email="es256@example.com", user_metadata={"full_name": "ES User"}
    )
    mock_auth_client = MagicMock()
    mock_auth_client.auth.get_user.return_value = MagicMock(user=mock_user)
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    token = "some.non-hs256.token"
    res = await auth_svc.verify_jwt_token(token)

    assert res["sub"] == user_id
    assert res["email"] == "es256@example.com"
    assert res["user_metadata"]["full_name"] == "ES User"


@pytest.mark.asyncio
async def test_verify_jwt_token_fallback_empty_user_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.get_user.return_value = MagicMock(user=None)
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(
        AuthError, match="Token inválido ou sessão expirada."
    ) as exc_info:
        await auth_svc.verify_jwt_token("some.token")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_jwt_token_fallback_exception_raises_401(
    auth_svc: AuthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_auth_client = MagicMock()
    mock_auth_client.auth.get_user.side_effect = Exception("SDK connection refused")
    monkeypatch.setattr(auth_svc, "_create_raw_client", lambda: mock_auth_client)

    with pytest.raises(AuthError, match="Token inválido ou expirado.") as exc_info:
        await auth_svc.verify_jwt_token("some.token")
    assert exc_info.value.status_code == 401


# --- update_auth_user ---


@pytest.mark.asyncio
async def test_update_auth_user_no_attributes_returns_early(
    auth_svc: AuthService,
) -> None:
    user_id = uuid.uuid4()
    result = await auth_svc.update_auth_user(user_id)
    assert result == {"id": str(user_id)}


@pytest.mark.asyncio
async def test_update_auth_user_success_with_password_and_fullname(
    auth_svc: AuthService,
) -> None:
    user_id = uuid.uuid4()
    mock_user = MagicMock(
        id=str(user_id),
        email="updated@example.com",
        user_metadata={"full_name": "Updated Name"},
    )
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.update_user_by_id.return_value = MagicMock(
        user=mock_user
    )
    auth_svc._admin_client = mock_admin_client

    result = await auth_svc.update_auth_user(
        user_id, password="newpassword123", full_name="Updated Name"
    )

    assert result["id"] == user_id
    assert result["email"] == "updated@example.com"
    assert result["full_name"] == "Updated Name"
    mock_admin_client.auth.admin.update_user_by_id.assert_called_once_with(
        str(user_id),
        {
            "password": "newpassword123",
            "user_metadata": {"full_name": "Updated Name"},
        },
    )


@pytest.mark.asyncio
async def test_update_auth_user_when_response_is_empty_raises_autherror(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.update_user_by_id.return_value = None
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(
        AuthError, match="Falha ao atualizar usuário no provedor de autenticação."
    ):
        await auth_svc.update_auth_user(uuid.uuid4(), password="newpassword")


@pytest.mark.asyncio
async def test_update_auth_user_when_sdk_raises_exception(
    auth_svc: AuthService,
) -> None:
    mock_admin_client = MagicMock()
    mock_admin_client.auth.admin.update_user_by_id.side_effect = RuntimeError(
        "Provider timeout"
    )
    auth_svc._admin_client = mock_admin_client

    with pytest.raises(
        AuthError, match="Erro ao atualizar usuário no provedor: Provider timeout"
    ):
        await auth_svc.update_auth_user(uuid.uuid4(), full_name="New Name")
