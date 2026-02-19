"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    host: str = "0.0.0.0"
    port: int = 8003
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
    agent_hub_redis_url: str = "redis://localhost:6379/2"

    # Hatchet
    hatchet_client_token: str = ""
    hatchet_client_tls_strategy: str = "none"

    # Security
    agent_hub_encryption_key: str = ""  # Fernet key for credential encryption
    agent_hub_secret_key: str = ""  # Session secret
    internal_service_secret: str = ""  # Internal service auth (set via env)

    # CORS (comma-separated list via CORS_ORIGINS env var)
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3003",
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

    # API Keys
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    gemini_use_adc: bool = False  # Set to True to prefer ADC over API key
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""
    zhipu_api_key: str = ""
    minimax_api_key: str = ""

    # Neo4j (Graphiti knowledge graph)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = ""  # Empty for no auth
    neo4j_password: str = ""  # Empty for no auth

    # Session timeout configuration (in minutes)
    # Sessions idle longer than these thresholds are auto-completed
    session_timeout_completion: int = 30  # 30 minutes for one-off completions
    session_timeout_chat: int = 1440  # 24 hours for interactive chat
    session_timeout_roundtable: int = 1440  # 24 hours for multi-agent
    session_timeout_image_generation: int = 120  # 2 hours for image gen
    session_timeout_agent: int = 1440  # 24 hours for long-running agents


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance (cached for performance)
    """
    return Settings()


settings = get_settings()
