"""All settings come from environment variables (or a local .env file)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"

    # Database (Postgres with the pgvector extension, e.g. Supabase or docker)
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/rag"

    # Auth
    jwt_secret: str = "change-me-to-a-long-random-string-in-production"
    jwt_expire_minutes: int = 12 * 60
    admin_email: str = "admin@example.com"
    admin_password: str = "admin12345"

    # LLM (any OpenAI-compatible API: Groq, OpenAI, Ollama, ...)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = 60

    # Embeddings run locally, no API key needed
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # Documents
    storage_dir: str = "./data/uploads"
    max_upload_mb: int = 10
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Chat
    top_k: int = 5
    history_messages: int = 6


settings = Settings()
