"""Tests for credential resolution chain: explicit → CredentialManager → error."""

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

    def test_raises_when_cm_empty_and_no_explicit(self) -> None:
        """Raises ValueError when CM has no key and no explicit key provided."""
        from app.adapters.openai import OpenAIAdapter

        cm = CredentialManager.get_instance()
        cm._initialized = True
        # No key in cache

        try:
            with pytest.raises(ValueError, match=r"(?i)openai API key not configured"):
                OpenAIAdapter()
        finally:
            CredentialManager.reset()

    def test_raises_when_explicit_key_empty(self) -> None:
        """Raises ValueError when explicit key is empty string."""
        from app.adapters.openai import OpenAIAdapter

        cm = CredentialManager.get_instance()
        cm._initialized = True

        try:
            with pytest.raises(ValueError, match=r"(?i)openai API key not configured"):
                OpenAIAdapter(api_key="")
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
            assert adapter._last_api_key == "explicit-key"
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
            assert adapter._last_api_key == "from-cm"
        finally:
            CredentialManager.reset()

    @patch("app.adapters.gemini.genai")
    def test_falls_back_to_adc_when_cm_empty(self, mock_genai: MagicMock) -> None:
        """Falls back to ADC when CM has no key (no error raised)."""
        from app.adapters.gemini import GeminiAdapter

        cm = CredentialManager.get_instance()
        cm._initialized = True
        # No key in cache

        try:
            adapter = GeminiAdapter()
            assert adapter._auth_mode == "adc"
        finally:
            CredentialManager.reset()


class TestCredentialsAPIValidation:
    """Test that credentials API accepts all providers."""

    def test_valid_providers_includes_all(self) -> None:
        """VALID_PROVIDERS includes all provider types."""
        from app.api.credentials import VALID_PROVIDERS

        expected = {"claude", "codex", "gemini", "minimax", "openrouter", "openai", "xai", "zhipu"}
        assert expected == VALID_PROVIDERS
