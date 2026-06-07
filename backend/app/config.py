"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# ---------------------------------------------------------------------------
# Port allocation — single source of truth for Agent Hub.
# ---------------------------------------------------------------------------
AGENT_HUB_BACKEND_PORT = 8003
AGENT_HUB_FRONTEND_PORT = 3003
# Peer frontend ports allowed for CORS
SUMMITFLOW_FRONTEND_PORT = 3001
PORTFOLIO_FRONTEND_PORT = 3000
REDIS_PORT = 6379
ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILES = tuple(
    str(path)
    for path in (
        ROOT_DIR / ".env.local",
        ROOT_DIR / ".env",
        Path.home() / ".env.local",
    )
)


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Prefers repo-local env files, then falls back to ~/.env.local.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
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
    agent_hub_db_pool_size: int = Field(default=20, ge=1)
    agent_hub_db_max_overflow: int = Field(default=10, ge=0)
    agent_hub_db_pool_timeout: int = Field(default=30, ge=1)
    agent_hub_db_pool_recycle: int = Field(default=1800, ge=30)

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
    hatchet_client_host_port: str = "127.0.0.1:7070"
    hatchet_client_tls_strategy: str = "none"

    # Shared browser / web research infrastructure
    st_browser_host: str = ""
    web_search_searxng_url: str = ""
    web_fetch_browser_cdp_url: str = ""

    # Security
    agent_hub_encryption_key: str = ""  # Fernet key for credential encryption
    agent_hub_secret_key: str = ""  # Session secret
    internal_service_secret: str = ""  # Internal service auth (set via env)

    # First-party client registrations for standalone and companion installs
    agent_hub_dashboard_client_id: str = "agent-hub-dashboard"
    agent_hub_dashboard_request_source: str = "agent-hub-dashboard"
    agent_hub_telegram_client_id: str = "agent-hub-telegram-bot"
    summitflow_client_id: str = ""
    portfolio_client_id: str = ""
    monkey_fight_client_id: str = ""

    # Native Telegram config overrides
    agent_hub_telegram_bot_token: str = ""
    agent_hub_telegram_allowed_chat_ids: str = ""
    agent_hub_telegram_report_chat_id: str = ""

    @field_validator("agent_hub_dashboard_client_id", mode="before")
    @classmethod
    def default_dashboard_client_id(cls, v: str | None) -> str:
        """Treat blank env values as the built-in dashboard client id."""
        if v is None:
            return "agent-hub-dashboard"
        cleaned = v.strip()
        return cleaned or "agent-hub-dashboard"

    @field_validator("agent_hub_dashboard_request_source", mode="before")
    @classmethod
    def default_dashboard_request_source(cls, v: str | None) -> str:
        """Treat blank env values as the built-in dashboard request source."""
        if v is None:
            return "agent-hub-dashboard"
        cleaned = v.strip()
        return cleaned or "agent-hub-dashboard"

    @field_validator("agent_hub_telegram_client_id", mode="before")
    @classmethod
    def default_telegram_client_id(cls, v: str | None) -> str:
        """Treat blank env values as the built-in Telegram bot client id."""
        if v is None:
            return "agent-hub-telegram-bot"
        cleaned = v.strip()
        return cleaned or "agent-hub-telegram-bot"

    # CORS (comma-separated list via CORS_ORIGINS env var)
    cors_origins: Annotated[list[str], NoDecode] = [
        f"http://localhost:{PORTFOLIO_FRONTEND_PORT}",
        f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
        f"http://localhost:{AGENT_HUB_FRONTEND_PORT}",
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
    vapid_subject: str = "mailto:admin@example.com"

    # Optional provider credentials for standalone and Docker installs.
    # These are overlaid into the runtime credential cache at startup so
    # clean installs work without manual dashboard credential entry.
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    kimi_code_api_key: str = ""
    moonshot_api_key: str = ""
    minimax_api_key: str = ""
    xai_api_key: str = ""
    zhipu_api_key: str = ""
    nvidia_api_key: str = ""
    cloudflare_api_key: str = ""
    cloudflare_account_id: str = ""

    # Local OpenAI-compatible endpoint. Ollama exposes this at /v1 by default.
    local_openai_base_url: str = "http://127.0.0.1:11434/v1"
    local_openai_api_key: str = ""



@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance (cached for performance)
    """
    return Settings()


settings = get_settings()

for key, value in {
    "HATCHET_CLIENT_TOKEN": settings.hatchet_client_token,
    "HATCHET_CLIENT_HOST_PORT": settings.hatchet_client_host_port,
    "HATCHET_CLIENT_TLS_STRATEGY": settings.hatchet_client_tls_strategy,
}.items():
    if value:
        os.environ.setdefault(key, value)
