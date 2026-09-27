from app.core.config import settings
from app.services.runner.base import CodeRunnerProvider


def get_runner_provider() -> CodeRunnerProvider:
    """Factory para instanciar o provedor de execução de código configurado."""
    provider_name = (settings.RUNNER_PROVIDER or "judge0").lower()

    if provider_name == "judge0":
        from app.services.runner.judge0_provider import Judge0Provider

        return Judge0Provider()

    if provider_name == "piston":
        from app.services.runner.piston_provider import PistonProvider

        return PistonProvider()

    raise ValueError(f"Provedor de runner não suportado: '{provider_name}'")
