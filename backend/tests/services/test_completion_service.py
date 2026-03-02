"""Tests for CompletionService cost tracking."""

from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import CompletionResult
from app.constants.models import CLAUDE_SONNET
from app.services.completion.service import CompletionService
from app.services.completion.types import CompletionOptions, CompletionSource


@pytest.fixture
def mock_adapter():
    adapter = AsyncMock()
    adapter.complete = AsyncMock(
        return_value=CompletionResult(
            content="Hello!",
            provider="claude",
            model=CLAUDE_SONNET,
            input_tokens=100,
            output_tokens=50,
        )
    )
    return adapter


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
    async def test_cost_logged_for_voice_completion(self, mock_adapter, options):
        """CompletionService should log cost after successful completion."""
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.get_adapter",
                return_value=mock_adapter,
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
            )

    @pytest.mark.asyncio
    async def test_cost_not_logged_on_zero_tokens(self, mock_adapter, options):
        """Cost logging should skip when tokens are zero."""
        mock_adapter.complete = AsyncMock(
            return_value=CompletionResult(
                content="",
                provider="claude",
                model=CLAUDE_SONNET,
                input_tokens=0,
                output_tokens=0,
            )
        )
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.get_adapter",
                return_value=mock_adapter,
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
    async def test_cost_logging_failure_does_not_propagate(self, mock_adapter, options):
        """Cost logging failure should not affect completion result."""
        svc = CompletionService(db=None)

        with (
            patch(
                "app.services.completion.service.get_adapter",
                return_value=mock_adapter,
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
                side_effect=Exception("DB connection failed"),
            ),
        ):
            # Should NOT raise despite cost logging failure
            result = await svc.complete(options)
            assert result.content == "Hello!"
            assert result.input_tokens == 100
