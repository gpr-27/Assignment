"""All settings come from environment variables (or a local .env file)."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Database (Postgres, e.g. Supabase or docker)
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/attendance"

    # Auth
    jwt_secret: str = "change-me-to-a-long-random-string-in-production"
    jwt_expire_minutes: int = 12 * 60
    admin_email: str = "admin@example.com"
    admin_password: str = "admin12345"

    # LLM via Agent Router (Axon), OpenAI-compatible /v1/chat/completions (tool calling)
    llm_base_url: str = Field(
        default="https://agentrouter.org",
        validation_alias=AliasChoices("AXON_BASE_URL", "LLM_BASE_URL"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AXON_API_KEY", "AGENTROUTER_API_KEY", "LLM_API_KEY"),
    )
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = 60

    # Attendance rules
    timezone: str = "Asia/Kolkata"  # punch times are judged in this local time
    work_days: list[int] = [0, 1, 2, 3, 4]  # Monday=0 ... Sunday=6; other days don't count as absent
    max_report_days: int = 366


settings = Settings()
