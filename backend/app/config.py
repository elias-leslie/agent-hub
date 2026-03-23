"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Port allocation — single source of truth for Agent Hub.
# ---------------------------------------------------------------------------
AGENT_HUB_BACKEND_PORT = 8003
AGENT_HUB_FRONTEND_PORT = 3003
# Peer frontend ports allowed for CORS
SUMMITFLOW_FRONTEND_PORT = 3001
PORTFOLIO_FRONTEND_PORT = 3000
REDIS_PORT = 6379


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Loads from ~/.env.local by default.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = AGENT_HUB_BACKEND_PORT
    debug: bool = False
    log_level: str = "INFO"

    # Database
    agent_hub_db_url: str = ""

    @field_validator("agent_hub_db_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure agent_hub_db_url is provided."""
        if not v:
            raise ValueError("AGENT_HUB_DB_URL environment variable is required")
        return v

    # Redis
    agent_hub_redis_url: str = f"redis://localhost:{REDIS_PORT}/2"

    # Hatchet
    hatchet_client_token: str = ""
    hatchet_client_tls_strategy: str = "none"

    # Shared browser / web research infrastructure
    sf_browser_host: str = "192.168.8.234"
    web_search_searxng_url: str = ""
    web_fetch_browser_cdp_url: str = ""

    # Security
    agent_hub_encryption_key: str = ""  # Fernet key for credential encryption
    agent_hub_secret_key: str = ""  # Session secret
    internal_service_secret: str = ""  # Internal service auth (set via env)

    # CORS (comma-separated list via CORS_ORIGINS env var)
    cors_origins: list[str] = [
        f"http://localhost:{PORTFOLIO_FRONTEND_PORT}",
        f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
        f"http://localhost:{AGENT_HUB_FRONTEND_PORT}",
        "https://agent.summitflow.dev",
        "https://dev.summitflow.dev",
        "https://port.summitflow.dev",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS_ORIGINS from comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Web Push (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@summitflow.dev"



@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance (cached for performance)
    """
    return Settings()


settings = get_settings()
