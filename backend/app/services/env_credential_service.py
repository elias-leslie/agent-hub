"""Overlay provider API keys from env files into the runtime credential cache."""

from __future__ import annotations

from app.config import settings
from app.services.credential_manager import get_credential_manager


def _split_keys(raw: str) -> list[str]:
    values = [value.strip() for value in raw.replace("\n", ",").split(",")]
    return [value for value in values if value]


def load_env_credentials_into_cache() -> list[str]:
    """Load provider credentials from settings into the in-memory cache.

    This intentionally does not persist values to the database. Public installs
    commonly provide API keys through `.env` or container environment variables,
    and adapters should treat those credentials as first-class runtime inputs.
    """

    credential_manager = get_credential_manager()
    changed: list[str] = []

    single_value_credentials = [
        ("cloudflare", "api_key", settings.cloudflare_api_key),
        ("cloudflare", "account_id", settings.cloudflare_account_id),
        ("deepseek", "api_key", settings.deepseek_api_key),
        ("kimi-code", "api_key", settings.kimi_code_api_key),
        ("local", "api_key", settings.local_openai_api_key),
        ("minimax", "api_key", settings.minimax_api_key),
        ("moonshot", "api_key", settings.moonshot_api_key),
        ("nvidia", "api_key", settings.nvidia_api_key),
        ("openai", "api_key", settings.openai_api_key),
        ("openrouter", "api_key", settings.openrouter_api_key),
        ("xai", "api_key", settings.xai_api_key),
        ("zhipu", "api_key", settings.zhipu_api_key),
    ]

    for provider, credential_type, raw_value in single_value_credentials:
        value = raw_value.strip()
        if not value:
            continue
        if credential_manager.get(provider, credential_type) == value:
            continue
        credential_manager.set(provider, credential_type, value)
        changed.append(f"{provider}:{credential_type}")

    gemini_keys = _split_keys(settings.gemini_api_key)
    if gemini_keys:
        merged_keys: list[str] = []
        for key in [*gemini_keys, *credential_manager.get_api_keys("gemini")]:
            if key and key not in merged_keys:
                merged_keys.append(key)
        if merged_keys != credential_manager.get_api_keys("gemini"):
            credential_manager.set_api_keys("gemini", merged_keys)
            changed.append("gemini:api_key")

    return changed
