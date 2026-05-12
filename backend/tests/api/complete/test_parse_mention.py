"""Tests for parse_mention — @mention model override extraction."""

from __future__ import annotations

import pytest

from app.api.complete.helpers import parse_mention
from app.constants.models import PROVIDER_NAMES


class TestParseMentionAliases:
    """Test alias resolution (e.g. @sonnet -> claude-sonnet-4-6)."""

    def test_alias_sonnet(self) -> None:
        model, cleaned = parse_mention("@sonnet Explain this code")
        assert model is not None
        assert "sonnet" in model
        assert cleaned == "Explain this code"

    def test_alias_opus(self) -> None:
        model, cleaned = parse_mention("@opus Think carefully about this")
        assert model is not None
        assert "opus" in model
        assert cleaned == "Think carefully about this"

    def test_alias_flash(self) -> None:
        model, _cleaned = parse_mention("@flash Quick question")
        assert model is not None
        assert "flash" in model or "gemini" in model


class TestParseMentionProviderPrefixed:
    """Test provider-prefixed model references (e.g. @cloudflare/flux-1-schnell)."""

    @pytest.mark.parametrize("provider", list(PROVIDER_NAMES.keys()))
    def test_all_providers_recognized(self, provider: str) -> None:
        """Every provider in PROVIDER_NAMES must be recognized as a valid @mention prefix."""
        model, cleaned = parse_mention(f"@{provider}/test-model Hello")
        assert model == f"{provider}/test-model", (
            f"Provider '{provider}' not recognized by parse_mention. "
            f"If PROVIDER_NAMES has it, parse_mention should accept it."
        )
        assert cleaned == "Hello"

    def test_cloudflare_model(self) -> None:
        model, cleaned = parse_mention("@cloudflare/qwen2.5-coder-32b Say hello")
        assert model == "cloudflare/qwen2.5-coder-32b"
        assert cleaned == "Say hello"

    def test_nvidia_model(self) -> None:
        model, cleaned = parse_mention("@nvidia/flux-1-kontext-dev Describe this")
        assert model == "nvidia/flux-1-kontext-dev"
        assert cleaned == "Describe this"

    def test_minimax_model(self) -> None:
        model, cleaned = parse_mention("@minimax/MiniMax-M2.5 Hello world")
        assert model == "minimax/MiniMax-M2.5"
        assert cleaned == "Hello world"

    def test_openrouter_model(self) -> None:
        model, cleaned = parse_mention("@openrouter/some-model Test")
        assert model == "openrouter/some-model"
        assert cleaned == "Test"

    def test_openrouter_free_model(self) -> None:
        model, cleaned = parse_mention("@openrouter/arcee-ai/trinity-large-preview:free Test")
        assert model == "openrouter/arcee-ai/trinity-large-preview:free"
        assert cleaned == "Test"


class TestParseMentionExactCatalogIds:
    """Test exact catalog model IDs passed through @mention injection."""

    def test_exact_claude_model_id(self) -> None:
        model, cleaned = parse_mention("@claude-sonnet-4-6 Explain this code")
        assert model == "claude-sonnet-4-6"
        assert cleaned == "Explain this code"

    def test_exact_gemini_model_id(self) -> None:
        model, cleaned = parse_mention("@gemini-3-flash-preview Quick question")
        assert model == "gemini-3-flash-preview"
        assert cleaned == "Quick question"


class TestParseMentionCleaning:
    """Test that @mention is properly stripped from content."""

    def test_mention_at_start(self) -> None:
        _, cleaned = parse_mention("@sonnet Hello world")
        assert cleaned == "Hello world"

    def test_mention_in_middle(self) -> None:
        _, cleaned = parse_mention("Please use @sonnet for this task")
        assert "@" not in cleaned

    def test_provider_slash_model_cleaned(self) -> None:
        _, cleaned = parse_mention("@cloudflare/qwen2.5-coder-32b Say hello in 3 words")
        assert "cloudflare" not in cleaned
        assert "qwen" not in cleaned
        assert cleaned == "Say hello in 3 words"


class TestParseMentionNoMatch:
    """Test cases where no @mention should be detected."""

    def test_no_mention(self) -> None:
        model, cleaned = parse_mention("Just a normal message")
        assert model is None
        assert cleaned == "Just a normal message"

    def test_email_not_matched(self) -> None:
        model, _cleaned = parse_mention("Send to user@example.com")
        # "example" is not a provider, so should return None
        assert model is None

    def test_unknown_prefix(self) -> None:
        model, _ = parse_mention("@unknownprovider/some-model Hello")
        assert model is None

    def test_bare_provider_resolves_to_default(self) -> None:
        """Bare provider names like @claude resolve to the default model."""
        model, cleaned = parse_mention("@claude Say hello")
        assert model is not None
        assert "sonnet" in model or "claude" in model
        assert cleaned == "Say hello"

    def test_bare_gemini_resolves_to_default(self) -> None:
        """Bare provider names like @gemini resolve to the default model."""
        model, cleaned = parse_mention("@gemini Describe this")
        assert model is not None
        assert "flash" in model or "gemini" in model
        assert cleaned == "Describe this"


class TestParseMentionMultimodal:
    """Test with list-style content blocks."""

    def test_content_blocks(self) -> None:
        content = [{"type": "text", "text": "@cloudflare/qwen2.5-coder-32b Hello"}]
        model, cleaned = parse_mention(content)
        assert model == "cloudflare/qwen2.5-coder-32b"
        assert cleaned == "Hello"


class TestApplyMentionOverrideStripping:
    """Test that apply_mention_override strips @mention from request messages."""

    def test_mention_stripped_from_message(self) -> None:
        """@mention should be removed from message content after override."""
        from unittest.mock import patch

        from app.api.complete.schemas import CompletionRequest, MessageInput
        from app.routing.resolution import apply_mention_override

        request = CompletionRequest(
            messages=[MessageInput(role="user", content="@cloudflare/qwen2.5-coder-32b Hello")],
            agent_slug="chat",
            project_id="test",
        )
        with patch(
            "app.routing.resolution.get_provider",
            return_value="cloudflare",
        ):
            model, provider = apply_mention_override(request, "nvidia/some-default")

        assert model == "cloudflare/qwen2.5-coder-32b"
        assert provider == "cloudflare"
        # The @mention must be stripped from the message content
        assert request.messages[0].content == "Hello"

    def test_no_mention_leaves_message_unchanged(self) -> None:
        """Messages without @mention should not be modified."""
        from unittest.mock import patch

        from app.api.complete.schemas import CompletionRequest, MessageInput
        from app.routing.resolution import apply_mention_override

        request = CompletionRequest(
            messages=[MessageInput(role="user", content="Hello world")],
            agent_slug="chat",
            project_id="test",
        )
        with patch(
            "app.routing.resolution.get_provider",
            return_value="nvidia",
        ):
            model, _provider = apply_mention_override(request, "nvidia/some-model")

        assert model == "nvidia/some-model"
        assert request.messages[0].content == "Hello world"
