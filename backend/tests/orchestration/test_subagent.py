"""Tests for subagent spawning and management."""

from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import CompletionResult, Message
from app.services.orchestration.subagent import (
    SubagentConfig,
    SubagentManager,
    SubagentResult,
)


class TestSubagentConfig:
    """Tests for SubagentConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        from app.constants import OUTPUT_LIMIT_AGENTIC

        config = SubagentConfig(name="test")

        assert config.name == "test"
        assert config.provider == "claude"
        assert config.model is None
        assert config.system_prompt is None
        assert config.max_tokens == OUTPUT_LIMIT_AGENTIC  # 64000 for agentic workloads
        assert config.temperature == 1.0
        assert config.budget_tokens is None
        assert config.timeout_seconds == 300.0

    def test_custom_values(self):
        """Test custom configuration."""
        config = SubagentConfig(
            name="analyzer",
            provider="gemini",
            model="gemini-3-flash-preview",
            system_prompt="You are an analyzer.",
            max_tokens=2048,
            temperature=0.5,
            budget_tokens=8000,
            timeout_seconds=60.0,
        )

        assert config.provider == "gemini"
        assert config.model == "gemini-3-flash-preview"
        assert config.budget_tokens == 8000


class TestSubagentResult:
    """Tests for SubagentResult dataclass."""

    def test_completed_result(self):
        """Test completed result structure."""
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="Hello world",
            status="completed",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        assert result.status == "completed"
        assert result.content == "Hello world"
        assert result.error is None

    def test_error_result(self):
        """Test error result structure."""
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="",
            status="error",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=0,
            output_tokens=0,
            error="Connection failed",
        )

        assert result.status == "error"
        assert result.error == "Connection failed"

    def test_result_with_thinking(self):
        """Test result with extended thinking."""
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="Answer",
            status="completed",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
            thinking_content="Let me think...",
            thinking_tokens=500,
        )

        assert result.thinking_content == "Let me think..."
        assert result.thinking_tokens == 500


class TestSubagentManager:
    """Tests for SubagentManager."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = SubagentManager()
        assert manager._default_claude_model == "claude-sonnet-4-5-20250514"
        assert manager._default_gemini_model == "gemini-3-flash-preview"

    def test_custom_default_models(self):
        """Test custom default model configuration."""
        manager = SubagentManager(
            default_claude_model="claude-opus-4-5",
            default_gemini_model="gemini-3-pro",
        )
        assert manager._default_claude_model == "claude-opus-4-5"
        assert manager._default_gemini_model == "gemini-3-pro"

    def test_get_adapter_claude(self):
        """Test getting Claude adapter."""
        manager = SubagentManager()
        adapter = manager._get_adapter("claude")
        assert adapter is not None

    def test_get_adapter_gemini(self):
        """Test getting Gemini adapter."""
        with patch("app.services.orchestration.subagent.GeminiAdapter"):
            manager = SubagentManager()
            adapter = manager._get_adapter("gemini")
            assert adapter is not None

    def test_get_adapter_caching(self):
        """Test adapter caching."""
        manager = SubagentManager()
        adapter1 = manager._get_adapter("claude")
        adapter2 = manager._get_adapter("claude")
        assert adapter1 is adapter2

    def test_get_adapter_unknown(self):
        """Test error for unknown provider."""
        manager = SubagentManager()
        with pytest.raises(ValueError, match="Unknown provider"):
            manager._get_adapter("unknown")

    @pytest.mark.asyncio
    async def test_spawn_success(self):
        """Test successful subagent spawn."""
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        mock_result = CompletionResult(
            content="Test response",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await manager.spawn(
                task="Hello, please respond.",
                config=config,
            )

            assert result.status == "completed"
            assert result.content == "Test response"
            assert result.input_tokens == 100
            assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_spawn_with_context(self):
        """Test spawn with context messages."""
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        mock_result = CompletionResult(
            content="Context aware response",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=200,
            output_tokens=60,
        )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(return_value=mock_result),
        ) as mock_complete:
            context = [
                Message(role="user", content="Previous message"),
                Message(role="assistant", content="Previous response"),
            ]

            result = await manager.spawn(
                task="Continue the conversation.",
                config=config,
                context=context,
            )

            assert result.status == "completed"
            # Verify context was included in messages
            call_args = mock_complete.call_args
            messages = call_args.kwargs.get("messages")
            assert len(messages) >= 3  # context + task

    @pytest.mark.asyncio
    async def test_spawn_with_system_prompt(self):
        """Test spawn with custom system prompt."""
        manager = SubagentManager()
        config = SubagentConfig(
            name="test",
            system_prompt="You are a helpful assistant.",
        )

        mock_result = CompletionResult(
            content="Helpful response",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(return_value=mock_result),
        ) as mock_complete:
            await manager.spawn(
                task="Help me.",
                config=config,
            )

            # Verify system prompt was included
            call_args = mock_complete.call_args
            messages = call_args.kwargs.get("messages")
            assert messages[0].role == "system"
            assert "helpful assistant" in messages[0].content

    @pytest.mark.asyncio
    async def test_spawn_timeout(self):
        """Test spawn timeout handling."""
        import asyncio

        manager = SubagentManager()
        config = SubagentConfig(name="test", timeout_seconds=0.1)

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(1)
            return CompletionResult(
                content="Too late",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=0,
                output_tokens=0,
            )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=slow_complete,
        ):
            result = await manager.spawn(
                task="This will timeout.",
                config=config,
            )

            assert result.status == "timeout"
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_spawn_error(self):
        """Test spawn error handling."""
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(side_effect=Exception("API error")),
        ):
            result = await manager.spawn(
                task="This will error.",
                config=config,
            )

            assert result.status == "error"
            assert "API error" in result.error

    @pytest.mark.asyncio
    async def test_spawn_with_trace_id(self):
        """Test spawn with trace ID."""
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        mock_result = CompletionResult(
            content="Traced response",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(return_value=mock_result),
        ):
            result = await manager.spawn(
                task="Traced task.",
                config=config,
                trace_id="abc123trace",
            )

            # Trace ID should be in result
            assert result.trace_id is not None

    @pytest.mark.asyncio
    async def test_spawn_background(self):
        """Test background subagent spawning."""
        manager = SubagentManager()
        config = SubagentConfig(name="background")

        mock_result = CompletionResult(
            content="Background response",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=50,
        )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=AsyncMock(return_value=mock_result),
        ):
            subagent_id = await manager.spawn_background(
                task="Background task.",
                config=config,
            )

            assert subagent_id is not None
            assert manager.active_count == 1

            # Get result
            result = await manager.get_result(subagent_id)
            assert result is not None
            assert result.status == "completed"
            assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_cancel_background(self):
        """Test canceling background subagent."""
        import asyncio

        manager = SubagentManager()
        config = SubagentConfig(name="cancellable", timeout_seconds=10)

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return CompletionResult(
                content="Never happens",
                provider="claude",
                model="claude-sonnet-4-5",
                input_tokens=0,
                output_tokens=0,
            )

        with patch.object(
            manager._get_adapter("claude"),
            "complete",
            new=slow_complete,
        ):
            subagent_id = await manager.spawn_background(
                task="Will be cancelled.",
                config=config,
            )

            assert manager.active_count == 1

            # Cancel it
            cancelled = manager.cancel(subagent_id)
            assert cancelled is True
            assert manager.active_count == 0

    def test_cancel_nonexistent(self):
        """Test canceling non-existent subagent."""
        manager = SubagentManager()
        cancelled = manager.cancel("nonexistent")
        assert cancelled is False
