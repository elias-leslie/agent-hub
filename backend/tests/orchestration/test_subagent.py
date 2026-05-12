"""Tests for subagent spawning and management."""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.types import CompletionInternalResult
from app.constants.models import CLAUDE_OPUS, CLAUDE_SONNET, GEMINI_FLASH
from app.services.llm_messages import Message
from app.services.orchestration.subagent import (
    SubagentConfig,
    SubagentManager,
    SubagentResult,
)


def _make_internal_result(
    *,
    content: str = "Test response",
    provider: str = "claude",
    model: str = CLAUDE_SONNET,
    input_tokens: int = 100,
    output_tokens: int = 50,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
) -> CompletionInternalResult:
    return CompletionInternalResult(
        content=content,
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason="stop",
        session_id="ephemeral:test",
        memory_uuids=[],
        cited_uuids=[],
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
    )


class TestSubagentConfig:
    def test_default_values(self):
        config = SubagentConfig(name="test")

        assert config.name == "test"
        assert config.provider == "claude"
        assert config.model is None
        assert config.system_prompt is None
        assert config.temperature == 1.0
        assert config.thinking_level is None
        assert config.timeout_seconds is None

    def test_custom_values(self):
        config = SubagentConfig(
            name="analyzer",
            provider="gemini",
            model=GEMINI_FLASH,
            system_prompt="You are an analyzer.",
            temperature=0.5,
            thinking_level="low",
            timeout_seconds=60.0,
        )

        assert config.provider == "gemini"
        assert config.model == GEMINI_FLASH
        assert config.thinking_level == "low"


class TestSubagentResult:
    def test_completed_result(self):
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="Hello world",
            status="completed",
            provider="claude",
            model=CLAUDE_SONNET,
            input_tokens=100,
            output_tokens=50,
        )

        assert result.status == "completed"
        assert result.content == "Hello world"
        assert result.error is None

    def test_error_result(self):
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="",
            status="error",
            provider="claude",
            model=CLAUDE_SONNET,
            input_tokens=0,
            output_tokens=0,
            error="Connection failed",
        )

        assert result.status == "error"
        assert result.error == "Connection failed"

    def test_result_with_thinking(self):
        result = SubagentResult(
            subagent_id="abc123",
            name="test",
            content="Answer",
            status="completed",
            provider="claude",
            model=CLAUDE_SONNET,
            input_tokens=100,
            output_tokens=50,
            thinking_content="Let me think...",
            thinking_tokens=500,
        )

        assert result.thinking_content == "Let me think..."
        assert result.thinking_tokens == 500


class TestSubagentManager:
    def test_initialization(self):
        from app.constants import CLAUDE_SONNET, GEMINI_FLASH

        manager = SubagentManager()
        assert manager._default_claude_model == CLAUDE_SONNET
        assert manager._default_gemini_model == GEMINI_FLASH

    def test_custom_default_models(self):
        manager = SubagentManager(
            default_claude_model=CLAUDE_OPUS,
            default_gemini_model="gemini-3-pro",
        )
        assert manager._default_claude_model == CLAUDE_OPUS
        assert manager._default_gemini_model == "gemini-3-pro"

    @pytest.mark.asyncio
    async def test_spawn_success(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result()),
        ):
            result = await manager.spawn(task="Hello, please respond.", config=config)

            assert result.status == "completed"
            assert result.content == "Test response"
            assert result.input_tokens == 100
            assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_spawn_with_context(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test", context_mode="full")

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result(content="Context aware response", input_tokens=200, output_tokens=60)),
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
            call_args = mock_complete.call_args
            messages = call_args.kwargs.get("messages")
            assert len(messages) >= 3

    @pytest.mark.asyncio
    async def test_spawn_with_context_defaults_to_focused_brief(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test", max_context_messages=2, max_context_chars=120)

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result(content="Focused response", input_tokens=120, output_tokens=40)),
        ) as mock_complete:
            context = [
                Message(role="system", content="Parent system rules."),
                Message(role="user", content="First parent request."),
                Message(role="assistant", content="Intermediate parent reply."),
                Message(role="user", content="Most recent parent request."),
            ]

            await manager.spawn(
                task="Continue the conversation.",
                config=config,
                context=context,
            )

            messages = mock_complete.call_args.kwargs["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "user"
            assert "Selected parent context:" in messages[0]["content"]
            assert "Parent system rules." not in messages[0]["content"]
            assert "First parent request." not in messages[0]["content"]
            assert "Intermediate parent reply." in messages[0]["content"]
            assert "Most recent parent request." in messages[0]["content"]
            assert messages[1]["content"] == "Continue the conversation."

    @pytest.mark.asyncio
    async def test_spawn_with_system_prompt(self):
        manager = SubagentManager()
        config = SubagentConfig(
            name="test",
            system_prompt="You are a helpful assistant.",
        )

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result(content="Helpful response")),
        ) as mock_complete:
            await manager.spawn(task="Help me.", config=config)

            call_args = mock_complete.call_args
            messages = call_args.kwargs.get("messages")
            assert messages is not None
            assert messages[0]["role"] == "system"
            assert "helpful assistant" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_spawn_timeout(self):
        import asyncio

        manager = SubagentManager()
        config = SubagentConfig(name="test", timeout_seconds=0.1)

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(1)
            return _make_internal_result(content="Too late", input_tokens=0, output_tokens=0)

        with patch(
            "app.api.complete.core.complete_internal",
            new=slow_complete,
        ):
            result = await manager.spawn(task="This will timeout.", config=config)

            assert result.status == "timeout"
            assert result.error is not None
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_spawn_error(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(side_effect=Exception("API error")),
        ):
            result = await manager.spawn(task="This will error.", config=config)

            assert result.status == "error"
            assert result.error is not None
            assert "API error" in result.error

    @pytest.mark.asyncio
    async def test_spawn_with_trace_id(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result(content="Traced response")),
        ):
            result = await manager.spawn(
                task="Traced task.",
                config=config,
                trace_id="abc123trace",
            )

            assert result.trace_id is not None

    @pytest.mark.asyncio
    async def test_spawn_background(self):
        manager = SubagentManager()
        config = SubagentConfig(name="background")

        with patch(
            "app.api.complete.core.complete_internal",
            new=AsyncMock(return_value=_make_internal_result(content="Background response")),
        ):
            subagent_id = await manager.spawn_background(task="Background task.", config=config)

            assert subagent_id is not None
            assert manager.active_count == 1

            result = await manager.get_result(subagent_id)
            assert result is not None
            assert result.status == "completed"
            assert manager.active_count == 0

    @pytest.mark.asyncio
    async def test_cancel_background(self):
        import asyncio

        manager = SubagentManager()
        config = SubagentConfig(name="cancellable", timeout_seconds=10)

        async def slow_complete(*args, **kwargs):
            await asyncio.sleep(10)
            return _make_internal_result(content="Never happens", input_tokens=0, output_tokens=0)

        with patch(
            "app.api.complete.core.complete_internal",
            new=slow_complete,
        ):
            subagent_id = await manager.spawn_background(task="Will be cancelled.", config=config)

            assert manager.active_count == 1

            cancelled = manager.cancel(subagent_id)
            assert cancelled is True
            assert manager.active_count == 0

    def test_cancel_nonexistent(self):
        manager = SubagentManager()
        cancelled = manager.cancel("nonexistent")
        assert cancelled is False


class TestSubagentCostTracking:
    @pytest.mark.asyncio
    async def test_cost_logged_when_project_id_set(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test", project_id="agent-hub")

        with (
            patch(
                "app.api.complete.core.complete_internal",
                new=AsyncMock(return_value=_make_internal_result()),
            ),
            patch(
                "app.services.orchestration.subagent_executor._log_subagent_cost",
                new_callable=AsyncMock,
            ) as mock_log_cost,
        ):
            result = await manager.spawn(task="Test task.", config=config)

            assert result.status == "completed"
            mock_log_cost.assert_called_once_with(
                project_id="agent-hub",
                provider="claude",
                model=CLAUDE_SONNET,
                input_tokens=100,
                output_tokens=50,
            )

    @pytest.mark.asyncio
    async def test_cost_not_logged_without_project_id(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test")

        with (
            patch(
                "app.api.complete.core.complete_internal",
                new=AsyncMock(return_value=_make_internal_result()),
            ),
            patch(
                "app.services.orchestration.subagent_executor._log_subagent_cost",
                new_callable=AsyncMock,
            ) as mock_log_cost,
        ):
            result = await manager.spawn(task="Test task.", config=config)

            assert result.status == "completed"
            mock_log_cost.assert_not_called()

    @pytest.mark.asyncio
    async def test_cost_not_logged_on_zero_tokens(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test", project_id="agent-hub")

        with (
            patch(
                "app.api.complete.core.complete_internal",
                new=AsyncMock(return_value=_make_internal_result(content="", input_tokens=0, output_tokens=0)),
            ),
            patch(
                "app.services.orchestration.subagent_executor._log_subagent_cost",
                new_callable=AsyncMock,
            ) as mock_log_cost,
        ):
            result = await manager.spawn(task="Test task.", config=config)

            assert result.status == "completed"
            mock_log_cost.assert_not_called()

    @pytest.mark.asyncio
    async def test_cost_logging_failure_does_not_propagate(self):
        manager = SubagentManager()
        config = SubagentConfig(name="test", project_id="agent-hub")

        with (
            patch(
                "app.api.complete.core.complete_internal",
                new=AsyncMock(return_value=_make_internal_result(content="Success")),
            ),
            patch(
                "app.services.orchestration.subagent_executor._log_subagent_cost",
                new_callable=AsyncMock,
                side_effect=Exception("DB connection failed"),
            ),
        ):
            result = await manager.spawn(task="Test task.", config=config)
            assert result.status == "completed"
            assert result.content == "Success"
