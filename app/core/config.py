from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    PROJECT_NAME: str = "CodeClass API"
    ENVIRONMENT: str = "development"
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/codeclass"
    )

    # Supabase Auth & Storage
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    # External Integrations - Code Runner Engine (Agnóstico)
    RUNNER_PROVIDER: str = "judge0"
    RUNNER_API_URL: str = "https://judge0-ce.p.rapidapi.com"
    RUNNER_API_KEY: str = ""
    RUNNER_TIMEOUT_SEC: float = 15.0

    # External Integrations - AI Engine
    AI_PROVIDER: str = "gemini"
    AI_API_KEY: str = ""
    AI_MODEL: str = "gemini-3.5-flash-lite"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
