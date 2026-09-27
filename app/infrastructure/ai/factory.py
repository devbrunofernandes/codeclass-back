from app.core.config import settings
from app.infrastructure.ai.base import AiProvider
from app.infrastructure.ai.gemini_provider import GeminiProvider


def get_ai_provider() -> AiProvider:
    """Factory para instanciar o provedor de IA ativo de acordo com as configurações."""
    provider_name = (settings.AI_PROVIDER or "gemini").lower()

    if provider_name == "gemini":
        return GeminiProvider()

    raise ValueError(f"Provedor de IA não suportado: '{provider_name}'")
