from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AiProvider(ABC):
    """Interface abstrata (Strategy Pattern) para provedores de inteligência artificial."""

    @abstractmethod
    async def generate_structured_insight(
        self,
        prompt: str,
        schema: type[T],
        temperature: float = 0.2,
    ) -> T:
        """Envia um prompt para o provedor de IA e retorna a resposta mapeada no schema Pydantic."""
