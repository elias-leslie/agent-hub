"""Per-provider runtime credential lookup for API keys.

Direct port of pi-mono ``packages/ai/src/env-api-keys.ts``.

Bun-specific ``/proc/self/environ`` fallback is dropped (Python doesn't have
the Bun-on-Linux empty-env bug). Vertex ADC + Bedrock multi-credential
detection is preserved. Agent Hub also accepts credentials loaded from the
approved DB-backed credential cache.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _get_api_key_env_vars(provider: str) -> tuple[str, ...] | None:
    if provider == "github-copilot":
        return ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")

    # ANTHROPIC_OAUTH_TOKEN takes precedence over ANTHROPIC_API_KEY.
    if provider == "anthropic":
        return ("ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY")

    env_map = {
        "openai": "OPENAI_API_KEY",
        "azure-openai-responses": "AZURE_OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "google": "GEMINI_API_KEY",
        "google-vertex": "GOOGLE_CLOUD_API_KEY",
        "groq": "GROQ_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "xai": "XAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "vercel-ai-gateway": "AI_GATEWAY_API_KEY",
        "zai": "ZAI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "minimax-cn": "MINIMAX_CN_API_KEY",
        "moonshotai": "MOONSHOT_API_KEY",
        "moonshotai-cn": "MOONSHOT_API_KEY",
        "huggingface": "HF_TOKEN",
        "fireworks": "FIREWORKS_API_KEY",
        "together": "TOGETHER_API_KEY",
        "opencode": "OPENCODE_API_KEY",
        "opencode-go": "OPENCODE_API_KEY",
        "kimi-code": "KIMI_CODE_API_KEY",
        "kimi-coding": "KIMI_API_KEY",
        "cloudflare": "CLOUDFLARE_API_KEY",
        "cloudflare-workers-ai": "CLOUDFLARE_API_KEY",
        "cloudflare-ai-gateway": "CLOUDFLARE_API_KEY",
        "xiaomi": "XIAOMI_API_KEY",
        "xiaomi-token-plan-cn": "XIAOMI_TOKEN_PLAN_CN_API_KEY",
        "xiaomi-token-plan-ams": "XIAOMI_TOKEN_PLAN_AMS_API_KEY",
        "xiaomi-token-plan-sgp": "XIAOMI_TOKEN_PLAN_SGP_API_KEY",
    }
    env_var = env_map.get(provider)
    return (env_var,) if env_var else None


_cached_vertex_adc_credentials_exists: bool | None = None


def _has_vertex_adc_credentials() -> bool:
    global _cached_vertex_adc_credentials_exists
    if _cached_vertex_adc_credentials_exists is not None:
        return _cached_vertex_adc_credentials_exists

    gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if gac_path:
        _cached_vertex_adc_credentials_exists = Path(gac_path).exists()
    else:
        default_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
        _cached_vertex_adc_credentials_exists = default_path.exists()
    return _cached_vertex_adc_credentials_exists


def find_env_keys(provider: str) -> list[str] | None:
    """Return env-var names that currently hold a value for ``provider``.

    Excludes ambient credentials (AWS profiles, IAM, Google ADC). Returns
    ``None`` if no key is set.
    """

    env_vars = _get_api_key_env_vars(provider)
    if not env_vars:
        return None
    found = [name for name in env_vars if os.environ.get(name)]
    return found or None


def _credential_providers(provider: str) -> tuple[str, ...]:
    aliases = {
        "anthropic": ("anthropic", "claude"),
        "claude": ("claude", "anthropic"),
        "codex": ("codex",),
        "google": ("gemini", "google"),
        "gemini": ("gemini", "google"),
        "google-generative-ai": ("gemini", "google"),
        "cloudflare": ("cloudflare",),
        "cloudflare-workers-ai": ("cloudflare",),
        "cloudflare-ai-gateway": ("cloudflare",),
        "kimi-code": ("kimi-code", "kimi-coding"),
        "kimi-coding": ("kimi-code", "kimi-coding"),
        "moonshotai": ("moonshot", "moonshotai"),
        "moonshotai-cn": ("moonshot", "moonshotai-cn"),
    }
    return aliases.get(provider, (provider,))


def _get_cached_api_key(provider: str) -> str | None:
    from app.services.credential_manager import get_credential_manager

    manager = get_credential_manager()
    for candidate in _credential_providers(provider):
        if candidate in {"anthropic", "claude", "codex"}:
            oauth_token = manager.get(candidate, "oauth_token")
            if oauth_token:
                return _extract_access_token(oauth_token)
        api_key = manager.get_api_key(candidate)
        if api_key:
            return api_key
    return None


def _extract_access_token(raw_value: str) -> str:
    try:
        data = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        return raw_value
    if not isinstance(data, dict):
        return raw_value
    token = data.get("access_token")
    return token if isinstance(token, str) and token else raw_value


def get_env_api_key(provider: str) -> str | None:
    """Return the API key for ``provider`` from env/cache, or ``None``.

    Special cases:

    * ``google-vertex`` and ``amazon-bedrock`` may authenticate via ambient
      credentials (ADC, AWS profiles, IRSA, …); when those are detected,
      ``"<authenticated>"`` is returned as a sentinel.
    """

    env_keys = find_env_keys(provider)
    if env_keys:
        return os.environ.get(env_keys[0])

    cached_key = _get_cached_api_key(provider)
    if cached_key:
        return cached_key

    if provider == "google-vertex":
        has_credentials = _has_vertex_adc_credentials()
        has_project = bool(
            os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
        )
        has_location = bool(os.environ.get("GOOGLE_CLOUD_LOCATION"))
        if has_credentials and has_project and has_location:
            return "<authenticated>"

    # Amazon Bedrock supports multiple credential sources:
    #   1. AWS_PROFILE — named profile from ~/.aws/credentials
    #   2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY — standard IAM keys
    #   3. AWS_BEARER_TOKEN_BEDROCK — Bedrock bearer token
    #   4. AWS_CONTAINER_CREDENTIALS_RELATIVE_URI — ECS task roles
    #   5. AWS_CONTAINER_CREDENTIALS_FULL_URI — ECS task roles (full URI)
    #   6. AWS_WEB_IDENTITY_TOKEN_FILE — IRSA
    if provider == "amazon-bedrock" and (
        os.environ.get("AWS_PROFILE")
        or (os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
        or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        or os.environ.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        or os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
        or os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE")
    ):
        return "<authenticated>"

    return None


__all__ = ["find_env_keys", "get_env_api_key"]
