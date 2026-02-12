"""Tests for credential resolution chain: explicit → CredentialManager → env var."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.credential_manager import CredentialManager


class TestOpenAICompatCredentialResolution:
    """Test credential resolution for OpenAI-compatible adapters."""

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_explicit_key_wins_over_cm(self, mock_openai_class: MagicMock) -> None:
        """Explicit api_key arg takes priority over CredentialManager."""
        from app.adapters.openai import OpenAIAdapter

        cm = CredentialManager.get_instance()
        cm._cache["openai:api_key"] = "from-cm"
        cm._initialized = True

        try:
            OpenAIAdapter(api_key="explicit-key")
            call_kwargs = mock_openai_class.call_args[1]
            assert call_kwargs["api_key"] == "explicit-key"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_cm_key_used_when_no_explicit(self, mock_openai_class: MagicMock) -> None:
        """CredentialManager key used when no explicit key provided."""
        from app.adapters.openai import OpenAIAdapter

        cm = CredentialManager.get_instance()
        cm._cache["openai:api_key"] = "from-cm"
        cm._initialized = True

        try:
            OpenAIAdapter()
            call_kwargs = mock_openai_class.call_args[1]
            assert call_kwargs["api_key"] == "from-cm"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.openai.settings")
    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_env_var_fallback_when_cm_empty(
        self, mock_openai_class: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Falls back to env var (settings) when CM has no key."""
        from app.adapters.openai import OpenAIAdapter

        mock_settings.openai_api_key = "from-env"

        cm = CredentialManager.get_instance()
        cm._initialized = True
        # No key in cache

        try:
            OpenAIAdapter()
            call_kwargs = mock_openai_class.call_args[1]
            assert call_kwargs["api_key"] == "from-env"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.openai.settings")
    def test_raises_when_all_empty(self, mock_settings: MagicMock) -> None:
        """Raises ValueError when explicit, CM, and env var are all empty."""
        from app.adapters.openai import OpenAIAdapter

        mock_settings.openai_api_key = ""

        cm = CredentialManager.get_instance()
        cm._initialized = True

        try:
            with pytest.raises(ValueError, match="(?i)openai API key not configured"):
                OpenAIAdapter()
        finally:
            CredentialManager.reset()

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_cm_not_initialized_skips_lookup(self, mock_openai_class: MagicMock) -> None:
        """Skips CM lookup when not initialized (startup race condition)."""
        from app.adapters.openai import OpenAIAdapter

        cm = CredentialManager.get_instance()
        cm._initialized = False
        cm._cache["openai:api_key"] = "should-be-ignored"

        try:
            OpenAIAdapter(api_key="explicit-key")
            call_kwargs = mock_openai_class.call_args[1]
            assert call_kwargs["api_key"] == "explicit-key"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.openai_compat.AsyncOpenAI")
    def test_resolution_works_for_all_providers(self, mock_openai_class: MagicMock) -> None:
        """Each OpenAI-compatible adapter resolves from CM using its provider name."""
        from app.adapters.openrouter import OpenRouterAdapter
        from app.adapters.xai import XAIAdapter
        from app.adapters.zhipu import ZhipuAdapter

        for adapter_cls, provider in [
            (OpenRouterAdapter, "openrouter"),
            (XAIAdapter, "xai"),
            (ZhipuAdapter, "zhipu"),
        ]:
            cm = CredentialManager.get_instance()
            cm._cache[f"{provider}:api_key"] = f"cm-key-{provider}"
            cm._initialized = True

            try:
                adapter_cls()
                call_kwargs = mock_openai_class.call_args[1]
                assert call_kwargs["api_key"] == f"cm-key-{provider}"
            finally:
                CredentialManager.reset()


class TestGeminiCredentialResolution:
    """Test credential resolution for Gemini adapter."""

    @patch("app.adapters.gemini.genai")
    def test_explicit_key_wins_over_cm(self, mock_genai: MagicMock) -> None:
        """Explicit api_key arg takes priority over CredentialManager."""
        from app.adapters.gemini import GeminiAdapter

        cm = CredentialManager.get_instance()
        cm._cache["gemini:api_key"] = "from-cm"
        cm._initialized = True

        try:
            adapter = GeminiAdapter(api_key="explicit-key")
            assert adapter._api_key == "explicit-key"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.gemini.genai")
    def test_cm_key_used_when_no_explicit(self, mock_genai: MagicMock) -> None:
        """CredentialManager key used when no explicit key provided."""
        from app.adapters.gemini import GeminiAdapter

        cm = CredentialManager.get_instance()
        cm._cache["gemini:api_key"] = "from-cm"
        cm._initialized = True

        try:
            adapter = GeminiAdapter()
            assert adapter._api_key == "from-cm"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.gemini.settings")
    @patch("app.adapters.gemini.genai")
    def test_env_var_fallback_when_cm_empty(
        self, mock_genai: MagicMock, mock_settings: MagicMock
    ) -> None:
        """Falls back to env var (settings) when CM has no key."""
        from app.adapters.gemini import GeminiAdapter

        mock_settings.gemini_api_key = "from-env"

        cm = CredentialManager.get_instance()
        cm._initialized = True

        try:
            adapter = GeminiAdapter()
            assert adapter._api_key == "from-env"
        finally:
            CredentialManager.reset()


class TestCredentialsAPIValidation:
    """Test that credentials API accepts all 6 providers."""

    def test_valid_providers_includes_all(self) -> None:
        """VALID_PROVIDERS includes all 6 agent types."""
        from app.api.credentials import VALID_PROVIDERS

        expected = {"claude", "gemini", "openrouter", "openai", "xai", "zhipu"}
        assert VALID_PROVIDERS == expected
