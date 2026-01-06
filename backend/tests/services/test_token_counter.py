"""Tests for token counter service."""

import pytest

from app.services.token_counter import (
    count_message_tokens,
    count_tokens,
    estimate_cost,
    estimate_request,
    get_context_limit,
)


class TestCountTokens:
    """Tests for token counting."""

    def test_empty_string(self):
        """Test empty string returns 0."""
        assert count_tokens("") == 0

    def test_simple_text(self):
        """Test simple text counting."""
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 10  # Should be around 4 tokens

    def test_longer_text(self):
        """Test longer text proportionally more tokens."""
        short = count_tokens("Hello")
        long = count_tokens("Hello, this is a much longer sentence with more words.")
        assert long > short


class TestCountMessageTokens:
    """Tests for message token counting."""

    def test_single_message(self):
        """Test single message counting."""
        messages = [{"role": "user", "content": "Hello"}]
        tokens = count_message_tokens(messages)
        assert tokens > 0

    def test_multiple_messages(self):
        """Test multiple messages includes overhead."""
        single = [{"role": "user", "content": "Hello"}]
        multiple = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        single_tokens = count_message_tokens(single)
        multiple_tokens = count_message_tokens(multiple)
        assert multiple_tokens > single_tokens

    def test_system_message(self):
        """Test system message included."""
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        tokens = count_message_tokens(messages)
        assert tokens > count_message_tokens([{"role": "user", "content": "Hello"}])


class TestEstimateCost:
    """Tests for cost estimation."""

    def test_claude_sonnet_cost(self):
        """Test Claude Sonnet pricing."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-sonnet-4-5-20250514",
        )
        assert cost.input_cost_usd == 3.0
        assert cost.output_cost_usd == 15.0
        assert cost.total_cost_usd == 18.0

    def test_claude_haiku_cost(self):
        """Test Claude Haiku pricing (cheaper)."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-haiku-4-5-20250514",
        )
        assert cost.input_cost_usd == 0.25
        assert cost.output_cost_usd == 1.25
        assert cost.total_cost_usd == 1.5

    def test_cached_input_discount(self):
        """Test cached input tokens cost less."""
        without_cache = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="claude-sonnet-4-5",
            cached_input_tokens=0,
        )
        with_cache = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=100_000,
            model="claude-sonnet-4-5",
            cached_input_tokens=900_000,  # 90% cached
        )
        assert with_cache.total_cost_usd < without_cache.total_cost_usd


class TestEstimateRequest:
    """Tests for request estimation."""

    def test_basic_estimate(self):
        """Test basic request estimation."""
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        estimate = estimate_request(
            messages=messages,
            model="claude-sonnet-4-5",
            max_tokens=4096,
        )
        assert estimate.input_tokens > 0
        assert estimate.estimated_output_tokens > 0
        assert estimate.total_tokens == estimate.input_tokens + estimate.estimated_output_tokens
        assert estimate.estimated_cost_usd > 0
        assert estimate.context_usage_percent < 1.0  # Small message

    def test_context_warning_high_usage(self):
        """Test context warning for high usage."""
        # Create a very long message
        long_content = "Hello " * 50000  # ~50k tokens
        messages = [{"role": "user", "content": long_content}]
        estimate = estimate_request(
            messages=messages,
            model="claude-sonnet-4-5",
            max_tokens=4096,
        )
        # Should have a warning if using >50% context
        if estimate.context_usage_percent > 50:
            assert estimate.context_warning is not None

    def test_different_models_different_limits(self):
        """Test different models have different context limits."""
        messages = [{"role": "user", "content": "Hello"}]

        claude_estimate = estimate_request(messages, "claude-sonnet-4-5", 1000)
        gemini_estimate = estimate_request(messages, "gemini-2.0-flash", 1000)

        assert claude_estimate.context_limit == 200000
        assert gemini_estimate.context_limit == 1000000


class TestGetContextLimit:
    """Tests for context limit retrieval."""

    def test_claude_limit(self):
        """Test Claude context limit."""
        assert get_context_limit("claude-sonnet-4-5-20250514") == 200000

    def test_gemini_flash_limit(self):
        """Test Gemini Flash context limit."""
        assert get_context_limit("gemini-2.0-flash-exp") == 1000000

    def test_unknown_model_default(self):
        """Test unknown model falls back to sonnet limit."""
        limit = get_context_limit("unknown-model")
        # Falls back to claude-sonnet-4 which has 200k limit
        assert limit == 200000
