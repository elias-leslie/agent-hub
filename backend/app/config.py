"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
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
    # Keep few idle connections while preserving the existing 30-call burst
    # capacity used by concurrent session/status inspection.
    agent_hub_db_pool_size: int = Field(default=5, ge=1)
    agent_hub_db_max_overflow: int = Field(default=25, ge=0)
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

    # Cloudflare Access identity for the dashboard proxy. The AUD is the
    # agent.summitflow.dev Access application's tag (each app has its own).
    cloudflare_access_team_domain: str = ""
    agent_hub_cf_access_aud: str = ""
    agent_hub_owner_emails: str = Field(
        default="", validation_alias=AliasChoices("AGENT_HUB_OWNER_EMAILS", "SUMMITFLOW_OWNER_EMAILS")
    )
    # Owner by caller identity: a loopback caller is the owner only while loopback_is_owner is on
    # (AGENT_HUB_LOOPBACK_IS_OWNER, default on = today's behaviour). The owner can always prove it
    # with the token in agent_hub_owner_token_file (readable only by the owner), sent as
    # X-Agent-Hub-Owner-Token. Agents and apps keep their client-id access and never get the owner role.
    agent_hub_loopback_is_owner: bool = True
    agent_hub_owner_token_file: str = ""
    # SummitFlow's owner token file (SUMMITFLOW_OWNER_TOKEN_FILE). Agent Hub's own calls to the SummitFlow
    # API (backup summary, notifications) send it as X-SummitFlow-Owner-Token now that loopback alone is no owner.
    summitflow_owner_token_file: str = ""
    dashboard_ui_request_log_sample_rate: float = 0.1  # Fraction of internal-header UI requests logged to request_logs

    # First-party client registrations for standalone and companion installs
    agent_hub_dashboard_client_id: str = "agent-hub-dashboard"
    agent_hub_dashboard_request_source: str = "agent-hub-dashboard"
    summitflow_client_id: str = ""
    portfolio_client_id: str = ""
    jobinator_client_id: str = "ea338be9-55b1-4aa6-921e-6493014f6f8e"
    monkey_fight_client_id: str = ""
    # Clients allowed to move context between scopes (into or out of global or an
    # agent, or across projects). summitflow_client_id (SummitFlow and st) always is.
    # Correctness guard only: client ids are caller-asserted behind the shared
    # internal secret (see is_admin_client).
    agent_hub_admin_client_ids: tuple[str, ...] = ()

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

    # CORS (comma-separated list via CORS_ORIGINS env var)
    cors_origins: Annotated[list[str], NoDecode] = [
        f"http://localhost:{PORTFOLIO_FRONTEND_PORT}",
        f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
        f"http://localhost:{AGENT_HUB_FRONTEND_PORT}",
    ]

    # Host names the backend answers to (AGENT_HUB_TRUSTED_HOSTS); any other Host is refused (DNS rebinding).
    agent_hub_trusted_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "::1"]

    # Refusal categories a workflow run never hands to the next model in the agent chain; the step goes to the
    # owner instead (WORKFLOW_OWNER_ONLY_REFUSAL_CATEGORIES, JSON array or comma-separated).
    workflow_owner_only_refusal_categories: Annotated[list[str], NoDecode] = ["reasoning_extraction", "frontier_llm"]

    # Lets a workflow step definition inject a refusal after turn N (``test_hooks``) without contacting a provider's
    # safety classifier. Off outside tests; the engine ignores the option while this is false.
    workflow_test_hooks_enabled: bool = False

    @field_validator(
        "cors_origins", "agent_hub_trusted_hosts", "workflow_owner_only_refusal_categories", mode="before"
    )
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        """Parse CORS_ORIGINS / AGENT_HUB_TRUSTED_HOSTS from a JSON array, comma-separated string, or list."""
        if isinstance(v, str):
            if v.strip().startswith("["):
                return [str(origin).strip() for origin in json.loads(v) if str(origin).strip()]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

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

    # OpenCode Go subscription quota (unofficial endpoint; reported as-is, never faked).
    opencode_go_usage_url: str = "https://opencode.ai/zen/go/v1/usage"
    opencode_go_usage_cache_seconds: float = Field(default=60.0, ge=0)
    opencode_go_usage_timeout_seconds: float = Field(default=10.0, gt=0)

    # Local OpenAI-compatible endpoint. Ollama exposes this at /v1 by default.
    local_openai_base_url: str = "http://127.0.0.1:11434/v1"
    local_openai_api_key: str = ""
    # Ollama-compatible keep_alive for local Gemma 4 calls. This keeps the
    # model warm during a short critique burst, then unloads it from GPU after
    # the idle window instead of wasting VRAM indefinitely.
    local_gemma4_keep_alive: str = "5m"

    # Tool-result compression (Headroom). Master kill-switch (off by default) plus
    # a per-agent_slug opt-in allowlist. Compression only fires when the master is
    # on AND the request's agent_slug is in the comma-separated allowlist — see
    # app/llm/headroom_compress.py:compression_enabled_for.
    headroom_compress_tool_results: bool = False
    headroom_compress_agent_slugs: str = ""

    # Direct-tool output budgets (chars). Bash output above the inline limit is spilled to a
    # searchable scratch artifact and only a tail-weighted preview stays in context (Pi/opencode
    # keep the tail of command output; failures and summaries are at the end). read_file stops at
    # the byte cap with a continuation offset instead of returning an unbounded page.
    tool_output_inline_chars: int = Field(default=50_000, ge=1_000)
    tool_output_preview_chars: int = Field(default=4_000, ge=500)
    tool_output_preview_tail_share: float = Field(default=0.75, ge=0.0, le=1.0)
    tool_read_file_max_bytes: int = Field(default=50_000, ge=1_000)

    # Persistent Claude Code CLI sessions (app/llm/provider_support/claude_sessions.py).
    claude_session_idle_seconds: float = Field(default=600.0, gt=0)
    claude_session_pool_max: int = Field(default=8, ge=1)



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
