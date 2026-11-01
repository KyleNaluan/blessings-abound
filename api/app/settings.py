from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The single .env file lives at the repository root and is shared with docker compose and web/.
ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_ignore_empty=True,
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://thrift:thrift@localhost:5432/thrift"
    cors_origins: list[str] = ["http://localhost:5173"]

    local_storage_dir: Path = Path("storage")
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "photos"

    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: str | None = None
    # Second provider, used when the first one fails twice or cannot be reached.
    ai_fallback_base_url: str | None = None
    ai_fallback_model: str | None = None
    ai_fallback_api_key: str | None = None

    serpapi_api_key: str | None = None
    # The free plan allows 250 searches a month, so the default leaves a small margin.
    serpapi_monthly_budget: int = 240


@lru_cache
def get_settings() -> Settings:
    return Settings()
