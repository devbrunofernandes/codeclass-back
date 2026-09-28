import inspect
import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class CompensatingAction:
    """Representa uma ação compensatória unitária registrada."""

    def __init__(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        name: str | None = None,
    ) -> None:
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.name = name or getattr(
            func, "__qualname__", getattr(func, "__name__", str(func))
        )

    async def execute(self) -> None:
        """Executa a ação compensatória suportando funções síncronas e assíncronas."""
        res = self.func(*self.args, **self.kwargs)
        if inspect.isawaitable(res):
            await res


class CompensatingTransaction:
    """Gerenciador de contexto assíncrono para transações compensatórias (Saga Pattern).

    Garante que, se uma falha ocorrer durante operações locais no banco de dados,
    ações de rollback compensatório em serviços externos (como Supabase Auth)
    sejam executadas em ordem reversa (LIFO) com tolerância a falhas e logging detalhado.
    """

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db
        self._actions: list[CompensatingAction] = []
        self._executed = False

    def register(
        self,
        func: Callable[..., Any],
        *args: Any,
        name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Registra uma ação compensatória a ser executada em caso de falha."""
        self._actions.append(
            CompensatingAction(func=func, args=args, kwargs=kwargs, name=name)
        )

    def cancel(self) -> None:
        """Cancela/desarma todas as ações compensatórias pendentes."""
        self._actions.clear()

    async def rollback(self) -> None:
        """Executa explicitamente o rollback do banco e todas as ações compensatórias pendentes."""
        if self._executed:
            return
        self._executed = True

        if self._db is not None:
            try:
                await self._db.rollback()
            except Exception as db_err:  # noqa: BLE001
                logger.warning(
                    "Falha ao executar rollback no banco de dados: %s",
                    db_err,
                )

        while self._actions:
            action = self._actions.pop()
            try:
                logger.info("Executando ação compensatória: %s", action.name)
                await action.execute()
            except Exception as action_err:  # noqa: BLE001
                logger.warning(
                    "Falha ao executar ação compensatória '%s': %s",
                    action.name,
                    action_err,
                )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            await self.rollback()
        else:
            self._actions.clear()
        return False
