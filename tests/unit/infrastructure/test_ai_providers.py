from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.infrastructure.ai.factory import get_ai_provider
from app.infrastructure.ai.gemini_provider import GeminiProvider


class DummySchema(BaseModel):
    message: str
    score: float


def test_gemini_provider_get_client_without_api_key_raises_error():
    provider = GeminiProvider()
    with (
        patch("app.infrastructure.ai.gemini_provider.settings.AI_API_KEY", ""),
        pytest.raises(
            RuntimeError,
            match="Chave de API de IA",
        ),
    ):
        provider._get_client()


def test_gemini_provider_get_client_success():
    provider = GeminiProvider()
    with (
        patch("app.infrastructure.ai.gemini_provider.settings.AI_API_KEY", "test-key"),
        patch("app.infrastructure.ai.gemini_provider.genai.Client") as mock_client_cls,
    ):
        client = provider._get_client()
        mock_client_cls.assert_called_once_with(api_key="test-key")
        assert client == mock_client_cls.return_value
        # Chamada subsequente deve reutilizar o cliente em cache
        client2 = provider._get_client()
        assert client2 == client
        mock_client_cls.assert_called_once()


@pytest.mark.asyncio
async def test_gemini_provider_generate_structured_insight_parsed():
    provider = GeminiProvider()
    expected = DummySchema(message="Excelente", score=10.0)

    mock_response = MagicMock()
    mock_response.parsed = expected

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch.object(provider, "_get_client", return_value=mock_client):
        result = await provider.generate_structured_insight(
            prompt="Avalie",
            schema=DummySchema,
        )

    assert result == expected
    mock_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_provider_generate_structured_insight_fallback_json_text():
    provider = GeminiProvider()

    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = '{"message": "Bom trabalho", "score": 8.5}'

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch.object(provider, "_get_client", return_value=mock_client):
        result = await provider.generate_structured_insight(
            prompt="Avalie",
            schema=DummySchema,
        )

    assert result.message == "Bom trabalho"
    assert result.score == 8.5


@pytest.mark.asyncio
async def test_gemini_provider_generate_structured_insight_empty_response_raises_error():
    provider = GeminiProvider()

    mock_response = MagicMock()
    mock_response.parsed = None
    mock_response.text = ""

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with (
        patch.object(provider, "_get_client", return_value=mock_client),
        pytest.raises(RuntimeError, match="Resposta vazia recebida do provedor Gemini"),
    ):
        await provider.generate_structured_insight(
            prompt="Avalie",
            schema=DummySchema,
        )


def test_get_ai_provider_gemini():
    with patch("app.infrastructure.ai.factory.settings.AI_PROVIDER", "gemini"):
        provider = get_ai_provider()
        assert isinstance(provider, GeminiProvider)

    with patch("app.infrastructure.ai.factory.settings.AI_PROVIDER", "GEMINI"):
        provider = get_ai_provider()
        assert isinstance(provider, GeminiProvider)


def test_get_ai_provider_unsupported_raises_error():
    with (
        patch(
            "app.infrastructure.ai.factory.settings.AI_PROVIDER", "unsupported_provider"
        ),
        pytest.raises(ValueError, match="Provedor de IA não suportado"),
    ):
        get_ai_provider()
