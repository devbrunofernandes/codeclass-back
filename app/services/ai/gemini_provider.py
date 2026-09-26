import asyncio
import logging
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.base import AiProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GeminiProvider(AiProvider):
    """Implementação do AiProvider integrada à API do Google Gemini (Flash-Lite)."""

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not settings.AI_API_KEY:
                raise RuntimeError(
                    "Chave de API de IA (AI_API_KEY) não configurada no ambiente."
                )
            self._client = genai.Client(api_key=settings.AI_API_KEY)
        return self._client

    async def generate_structured_insight(
        self,
        prompt: str,
        schema: type[T],
        temperature: float = 0.2,
    ) -> T:
        client = self._get_client()

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
        )

        async with asyncio.timeout(30.0):
            response = await client.aio.models.generate_content(
                model=settings.AI_MODEL,
                contents=prompt,
                config=config,
            )

        if (
            hasattr(response, "parsed")
            and response.parsed is not None
            and isinstance(response.parsed, schema)
        ):
            return response.parsed

        if response.text:
            return schema.model_validate_json(response.text)

        raise RuntimeError("Resposta vazia recebida do provedor Gemini.")
