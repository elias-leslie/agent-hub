"""
Configuration management using pydantic-settings.
Loads from environment variables and ~/.env.local
"""

from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    # Database
    database_url: str = "postgresql://localhost/agent-hub"

    # Redis (for Celery)
    redis_url: str = "redis://localhost:6379/0"

    # API Keys (loaded from ~/.env.local)
    anthropic_api_key: str = ""

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL (Redis)."""
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend (Redis)."""
        return self.redis_url


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
