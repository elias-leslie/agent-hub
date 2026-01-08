"""
Configuration management using pydantic-settings.
Loads from environment variables and ~/.env.local
"""

from functools import lru_cache
from pathlib import Path

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
    log_level: str = "INFO"

    # Database
    agent_hub_db_url: str = "postgresql://localhost/agent_hub"

    # Redis
    agent_hub_redis_url: str = "redis://localhost:6379/2"

    # Security
    agent_hub_encryption_key: str = ""  # Fernet key for credential encryption
    agent_hub_secret_key: str = ""  # Session secret

    # CORS
    cors_origins: str = "http://localhost:3003"

    # API Keys
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # MCP Registry
    mcp_registry_url: str = "https://registry.modelcontextprotocol.io"
    mcp_local_servers: str = ""  # JSON list of local MCP servers to include
    mcp_registry_cache_ttl: int = 300  # Cache TTL in seconds (5 minutes)

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL (Redis)."""
        return self.agent_hub_redis_url

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend (Redis)."""
        return self.agent_hub_redis_url


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
