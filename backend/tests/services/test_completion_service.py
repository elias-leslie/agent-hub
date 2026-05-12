"""Tests for CompletionService cost tracking."""

from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.api.complete.types import CompletionInternalResult
from app.constants.models import CLAUDE_SONNET
from app.services.completion.service import CompletionService
from app.services.completion.types import CompletionOptions, CompletionSource


@pytest.fixture
def completion_result() -> CompletionInternalResult:
    return CompletionInternalResult(
        content="Hello!",
        provider="claude",
        model=CLAUDE_SONNET,
        input_tokens=100,
        output_tokens=50,
        finish_reason="stop",
        session_id="sess-test",
        memory_uuids=[],
        cited_uuids=[],
    )


@pytest.fixture
def options():
    return CompletionOptions(
        model=CLAUDE_SONNET,
        messages=[{"role": "user", "content": "Hi"}],
        project_id="voice-summitflow",
        source=CompletionSource.VOICE,
    )


class TestCompletionServiceCostTracking:
    """Tests for cost tracking in CompletionService."""

    @pytest.mark.asyncio
    async def test_cost_logged_for_voice_completion(self, completion_result, options):
        """CompletionService should log cost after successful completion."""
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.complete_internal",
                new=AsyncMock(return_value=completion_result),
            ),
            patch(
                "app.services.completion.service.inject_memory_context",
                new=AsyncMock(return_value=(options.messages, 0)),
            ),
            patch(
                "app.services.completion.service.handle_episode_storage",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.completion.service._log_completion_cost",
                new_callable=AsyncMock,
            ) as mock_log_cost,
        ):
            result = await svc.complete(options)

            assert result.content == "Hello!"
            mock_log_cost.assert_called_once_with(
                project_id="voice-summitflow",
                provider="claude",
                model=CLAUDE_SONNET,
                input_tokens=100,
                output_tokens=50,
                source="voice",
                session_id=ANY,
            )

    @pytest.mark.asyncio
    async def test_cost_not_logged_on_zero_tokens(self, options):
        """Cost logging should skip when tokens are zero."""
        zero_result = CompletionInternalResult(
            content="",
            provider="claude",
            model=CLAUDE_SONNET,
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
            session_id="sess-test",
            memory_uuids=[],
            cited_uuids=[],
        )
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.complete_internal",
                new=AsyncMock(return_value=zero_result),
            ),
            patch(
                "app.services.completion.service.inject_memory_context",
                new=AsyncMock(return_value=(options.messages, 0)),
            ),
            patch(
                "app.services.completion.service.handle_episode_storage",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.completion.service._log_completion_cost",
                new_callable=AsyncMock,
            ) as mock_log_cost,
        ):
            result = await svc.complete(options)

            assert result.content == ""
            mock_log_cost.assert_not_called()

    @pytest.mark.asyncio
    async def test_cost_logging_failure_does_not_propagate(self, completion_result, options):
        """Cost logging failure should not affect completion result."""
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.complete_internal",
                new=AsyncMock(return_value=completion_result),
            ),
            patch(
                "app.services.completion.service.inject_memory_context",
                new=AsyncMock(return_value=(options.messages, 0)),
            ),
            patch(
                "app.services.completion.service.handle_episode_storage",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.db.async_session",
                side_effect=Exception("DB connection failed"),
            ),
        ):
            # Should NOT raise despite cost logging failure
            result = await svc.complete(options)
            assert result.content == "Hello!"
            assert result.input_tokens == 100
