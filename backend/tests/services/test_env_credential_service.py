"""Tests for env-backed credential cache overlays."""

from __future__ import annotations

from unittest.mock import patch

from app.services.credential_manager import CredentialManager
from app.services.env_credential_service import load_env_credentials_into_cache


class TestLoadEnvCredentialsIntoCache:
    def setup_method(self) -> None:
        CredentialManager.reset()

    def test_loads_single_value_provider_keys_into_cache(self) -> None:
        with (
            patch(
                "app.services.env_credential_service.settings.openai_api_key",
                "openai-key",
            ),
            patch(
                "app.services.env_credential_service.settings.openrouter_api_key",
                "openrouter-key",
            ),
            patch(
                "app.services.env_credential_service.settings.kimi_code_api_key",
                "kimi-code-key",
            ),
            patch(
                "app.services.env_credential_service.settings.gemini_api_key",
                "",
            ),
        ):
            changed = load_env_credentials_into_cache()

        credential_manager = CredentialManager.get_instance()
        assert changed == [
            "kimi-code:api_key",
            "openai:api_key",
            "openrouter:api_key",
        ]
        assert credential_manager.get_api_key("kimi-code") == "kimi-code-key"
        assert credential_manager.get_api_key("openai") == "openai-key"
        assert credential_manager.get_api_key("openrouter") == "openrouter-key"

    def test_prepends_env_gemini_keys_ahead_of_cached_keys(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set_api_keys("gemini", ["cached-key"])

        with (
            patch(
                "app.services.env_credential_service.settings.openai_api_key",
                "",
            ),
            patch(
                "app.services.env_credential_service.settings.openrouter_api_key",
                "",
            ),
            patch(
                "app.services.env_credential_service.settings.kimi_code_api_key",
                "",
            ),
            patch(
                "app.services.env_credential_service.settings.gemini_api_key",
                "env-key-1, env-key-2",
            ),
        ):
            changed = load_env_credentials_into_cache()

        assert changed == ["gemini:api_key"]
        assert credential_manager.get_api_keys("gemini") == [
            "env-key-1",
            "env-key-2",
            "cached-key",
        ]

    def test_noops_when_env_values_match_existing_cache(self) -> None:
        credential_manager = CredentialManager.get_instance()
        credential_manager.set("openai", "api_key", "openai-key")

        with (
            patch(
                "app.services.env_credential_service.settings.openai_api_key",
                "openai-key",
            ),
            patch(
                "app.services.env_credential_service.settings.openrouter_api_key",
                "",
            ),
            patch(
                "app.services.env_credential_service.settings.kimi_code_api_key",
                "",
            ),
            patch(
                "app.services.env_credential_service.settings.gemini_api_key",
                "",
            ),
        ):
            changed = load_env_credentials_into_cache()

        assert changed == []
