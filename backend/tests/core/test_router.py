"""Tests for ModelRouter."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.base import (
    CircuitBreakerError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.services.router import (
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_THRESHOLD,
    THRASHING_THRESHOLD,
    CircuitState,
    ModelRouter,
)


@pytest.fixture
def mock_claude_adapter():
    """Create mock Claude adapter."""
    adapter = MagicMock()
    adapter.complete = AsyncMock(
        return_value=CompletionResult(
            content="Hello from Claude!",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
        )
    )
    return adapter


@pytest.fixture
def mock_gemini_adapter():
    """Create mock Gemini adapter."""
    adapter = MagicMock()
    adapter.complete = AsyncMock(
        return_value=CompletionResult(
            content="Hello from Gemini!",
            model="gemini-3-flash-preview",
            provider="gemini",
            input_tokens=8,
            output_tokens=4,
            finish_reason="STOP",
        )
    )
    return adapter


class TestModelRouter:
    """Tests for ModelRouter."""

    def test_init_default_chain(self):
        """Test default provider chain."""
        router = ModelRouter()
        assert router._provider_chain == ["claude", "gemini"]

    def test_init_custom_chain(self):
        """Test custom provider chain."""
        router = ModelRouter(provider_chain=["gemini", "claude"])
        assert router._provider_chain == ["gemini", "claude"]

    def test_determine_primary_provider_claude(self):
        """Test primary provider detection for Claude model."""
        router = ModelRouter()
        assert router._determine_primary_provider("claude-sonnet-4-5-20250514") == "claude"

    def test_determine_primary_provider_gemini(self):
        """Test primary provider detection for Gemini model."""
        router = ModelRouter()
        assert router._determine_primary_provider("gemini-3-flash-preview") == "gemini"

    def test_determine_primary_provider_unknown(self):
        """Test primary provider detection for unknown model."""
        router = ModelRouter()
        # Defaults to first in chain
        assert router._determine_primary_provider("unknown-model") == "claude"

    @pytest.mark.asyncio
    async def test_complete_primary_success(self, mock_claude_adapter, mock_gemini_adapter):
        """Test successful completion with primary provider."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.content == "Hello from Claude!"
        assert result.provider == "claude"
        mock_claude_adapter.complete.assert_called_once()
        mock_gemini_adapter.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_error(self, mock_claude_adapter, mock_gemini_adapter):
        """Test fallback when primary provider fails with rate limit."""
        # Make Claude fail with rate limit
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should fall back to Gemini
        assert result.content == "Hello from Gemini!"
        assert result.provider == "gemini"
        mock_claude_adapter.complete.assert_called_once()
        mock_gemini_adapter.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_retriable_error(self, mock_claude_adapter, mock_gemini_adapter):
        """Test fallback on retriable provider error."""
        mock_claude_adapter.complete = AsyncMock(
            side_effect=ProviderError("Server error", provider="claude", retriable=True)
        )

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert result.provider == "gemini"

    @pytest.mark.asyncio
    async def test_no_fallback_on_non_retriable_error(
        self, mock_claude_adapter, mock_gemini_adapter
    ):
        """Test that non-retriable errors don't trigger fallback."""
        mock_claude_adapter.complete = AsyncMock(
            side_effect=ProviderError("Auth error", provider="claude", retriable=False)
        )

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        with pytest.raises(ProviderError) as exc_info:
            await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert exc_info.value.provider == "claude"
        mock_gemini_adapter.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, mock_claude_adapter, mock_gemini_adapter):
        """Test error when all providers fail."""
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))
        mock_gemini_adapter.complete = AsyncMock(side_effect=RateLimitError("gemini"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        with pytest.raises(RateLimitError):
            await router.complete(messages, model="claude-sonnet-4-5-20250514")

    @pytest.mark.asyncio
    async def test_model_mapping_on_fallback(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that model is mapped when falling back."""
        mock_claude_adapter.complete = AsyncMock(side_effect=RateLimitError("claude"))

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Verify Gemini was called with mapped model
        call_kwargs = mock_gemini_adapter.complete.call_args.kwargs
        assert "gemini" in call_kwargs["model"].lower()

    @pytest.mark.asyncio
    async def test_config_error_fallback(self, mock_gemini_adapter):
        """Test fallback when primary has config error (missing API key)."""

        # Claude factory raises ValueError (missing API key)
        def claude_factory():
            raise ValueError("API key not configured")

        router = ModelRouter(
            adapter_factory={
                "claude": claude_factory,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should fall back to Gemini
        assert result.provider == "gemini"

    @pytest.mark.asyncio
    async def test_tier_selection_simple_prompt(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that simple prompts use tier 1 (haiku)."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hello")]
        await router.complete(messages, auto_tier=True)

        # Verify haiku model was selected for simple prompt
        call_kwargs = mock_claude_adapter.complete.call_args.kwargs
        assert "haiku" in call_kwargs["model"].lower()

    @pytest.mark.asyncio
    async def test_tier_selection_complex_prompt(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that complex prompts use higher tier (opus)."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [
            Message(
                role="user", content="Design the system architecture for a distributed database"
            )
        ]
        await router.complete(messages, auto_tier=True)

        # Verify opus model was selected for complex prompt
        call_kwargs = mock_claude_adapter.complete.call_args.kwargs
        assert "opus" in call_kwargs["model"].lower()


class TestThrashingDetection:
    """Tests for thrashing detection and circuit breaker."""

    def test_error_signature_computation(self):
        """Test that identical errors produce identical signatures."""
        router = ModelRouter()
        error1 = ProviderError("Server error", provider="claude", retriable=True)
        error2 = ProviderError("Server error", provider="claude", retriable=True)

        sig1 = router._compute_error_signature(error1, "claude", "claude-sonnet-4-5-20250514")
        sig2 = router._compute_error_signature(error2, "claude", "claude-sonnet-4-5-20250514")

        assert sig1 == sig2

    def test_different_errors_different_signatures(self):
        """Test that different errors produce different signatures."""
        router = ModelRouter()
        error1 = ProviderError("Server error", provider="claude", retriable=True)
        error2 = ProviderError("Different error", provider="claude", retriable=True)

        sig1 = router._compute_error_signature(error1, "claude", "claude-sonnet-4-5-20250514")
        sig2 = router._compute_error_signature(error2, "claude", "claude-sonnet-4-5-20250514")

        assert sig1 != sig2

    def test_thrashing_detection_counts_consecutive(self):
        """Test that thrashing detection counts consecutive identical errors."""
        router = ModelRouter()
        error = ProviderError("Server error", provider="claude", retriable=True)

        # Record same error multiple times
        count1 = router._record_error(error, "claude", "claude-sonnet-4-5-20250514")
        count2 = router._record_error(error, "claude", "claude-sonnet-4-5-20250514")
        count3 = router._record_error(error, "claude", "claude-sonnet-4-5-20250514")

        # Each identical error increments the count
        assert count1 == 1  # First error, no history
        assert count2 == 2  # Matches one in history
        assert count3 == 3  # Matches two in history

    def test_thrashing_detection_resets_on_different_error(self):
        """Test that thrashing count resets when different error occurs."""
        router = ModelRouter()
        error1 = ProviderError("Server error", provider="claude", retriable=True)
        error2 = ProviderError("Different error", provider="claude", retriable=True)

        router._record_error(error1, "claude", "claude-sonnet-4-5-20250514")
        router._record_error(error1, "claude", "claude-sonnet-4-5-20250514")
        count = router._record_error(error2, "claude", "claude-sonnet-4-5-20250514")

        # Different error resets count - doesn't match previous consecutive errors
        assert count == 1

    def test_circuit_state_initialization(self):
        """Test that circuit state starts CLOSED."""
        router = ModelRouter()
        state = router._get_circuit_state("claude")

        assert state.state == CircuitState.CLOSED
        assert state.consecutive_failures == 0
        assert state.last_error_signature is None

    def test_circuit_status_getter(self):
        """Test get_circuit_status returns all providers."""
        router = ModelRouter()
        status = router.get_circuit_status()

        assert "claude" in status
        assert "gemini" in status
        assert status["claude"]["state"] == "closed"
        assert status["gemini"]["state"] == "closed"

    def test_circuit_manual_reset(self):
        """Test manual circuit reset."""
        router = ModelRouter()
        # Set up an open circuit
        state = router._get_circuit_state("claude")
        state.state = CircuitState.OPEN
        state.consecutive_failures = 5

        router.reset_circuit("claude")

        new_state = router._get_circuit_state("claude")
        assert new_state.state == CircuitState.CLOSED
        assert new_state.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, mock_gemini_adapter):
        """Test that circuit breaker opens after consecutive failures."""
        error = ProviderError("Persistent error", provider="claude", retriable=True)
        mock_claude = MagicMock()
        mock_claude.complete = AsyncMock(side_effect=error)

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        messages = [Message(role="user", content="Hi")]

        # Make repeated failing requests until circuit opens
        for _i in range(CIRCUIT_BREAKER_THRESHOLD - 1):
            # Request should fall back to gemini
            result = await router.complete(messages, model="claude-sonnet-4-5-20250514")
            assert result.provider == "gemini"

        # Next failure should trigger circuit breaker
        with pytest.raises(CircuitBreakerError) as exc_info:
            await router.complete(messages, model="claude-sonnet-4-5-20250514")

        assert exc_info.value.consecutive_failures == CIRCUIT_BREAKER_THRESHOLD
        assert exc_info.value.provider == "claude"

    @pytest.mark.asyncio
    async def test_circuit_skips_open_provider(self, mock_gemini_adapter):
        """Test that requests skip providers with open circuit."""
        mock_claude = MagicMock()
        mock_claude.complete = AsyncMock()

        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        # Manually open circuit for claude
        state = router._get_circuit_state("claude")
        state.state = CircuitState.OPEN
        state.cooldown_until = time.time() + 100  # Far future
        state.consecutive_failures = 5
        state.last_error_signature = "test:sig"

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should skip claude and use gemini
        assert result.provider == "gemini"
        mock_claude.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_half_open_after_cooldown(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that circuit transitions to half-open after cooldown."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        # Set up open circuit with expired cooldown
        state = router._get_circuit_state("claude")
        state.state = CircuitState.OPEN
        state.cooldown_until = time.time() - 1  # Past
        state.consecutive_failures = 5

        messages = [Message(role="user", content="Hi")]
        result = await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Should try claude (half-open) and succeed
        assert result.provider == "claude"
        # State should be closed after success
        assert state.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_success_resets_circuit(self, mock_claude_adapter, mock_gemini_adapter):
        """Test that successful request resets circuit state."""
        router = ModelRouter(
            adapter_factory={
                "claude": lambda: mock_claude_adapter,
                "gemini": lambda: mock_gemini_adapter,
            }
        )

        # Build up some failures
        state = router._get_circuit_state("claude")
        state.consecutive_failures = 3
        state.last_error_signature = "test:sig"

        messages = [Message(role="user", content="Hi")]
        await router.complete(messages, model="claude-sonnet-4-5-20250514")

        # Success should reset state
        assert state.consecutive_failures == 0
        assert state.last_error_signature is None

    def test_thrashing_threshold_constant(self):
        """Test thrashing threshold value."""
        assert THRASHING_THRESHOLD == 2

    def test_circuit_breaker_threshold_constant(self):
        """Test circuit breaker threshold value."""
        assert CIRCUIT_BREAKER_THRESHOLD == 5

    def test_circuit_breaker_cooldown_constant(self):
        """Test circuit breaker cooldown value."""
        assert CIRCUIT_BREAKER_COOLDOWN == 60.0
