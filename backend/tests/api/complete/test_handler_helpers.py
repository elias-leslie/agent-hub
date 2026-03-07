"""Tests for completion handler helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.handler_helpers import save_and_track
from app.api.complete.schemas import CompletionRequest, MessageInput


@pytest.mark.asyncio
async def test_save_and_track_uses_model_used_for_events_and_cost() -> None:
    """When fallback is used, persistence should attribute to model_used."""
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hello")],
        project_id="test-project",
    )
    result = SimpleNamespace(
        content="done",
        input_tokens=11,
        output_tokens=13,
        thinking_content=None,
        thinking_tokens=None,
        cache_metrics=None,
    )
    db = AsyncMock()
    session = SimpleNamespace(
        status="active",
        provider="minimax",
        model="minimax/MiniMax-M2.5",
        models_used=[],
        providers_used=[],
        provider_metadata={},
    )

    with (
        patch("app.api.complete.handler_helpers.save_events", new_callable=AsyncMock) as mock_save_events,
        patch("app.api.complete.handler_helpers.estimate_cost", return_value=MagicMock(total_cost_usd=0.0)) as mock_cost,
        patch("app.api.complete.handler_helpers.log_token_usage", new_callable=AsyncMock) as mock_log_tokens,
        patch("app.api.complete.handler_helpers.publish_complete", new_callable=AsyncMock),
    ):
        await save_and_track(
            db=db,
            session=session,
            session_id="sess-1",
            request=request,
            result=result,
            resolved_model="xai/grok-4-1-fast-reasoning",
            model_used="claude-haiku-4-5",
            fallback_reason="TimeoutError: primary timed out",
            is_new_session=True,
        )

    assert mock_save_events.await_args.args[6] == "claude-haiku-4-5"
    assert mock_cost.call_args.args[2] == "claude-haiku-4-5"
    assert mock_log_tokens.await_args.args[2] == "claude-haiku-4-5"
    assert session.model == "claude-haiku-4-5"
    assert session.provider == "claude"
    assert "claude-haiku-4-5" in session.models_used
    assert "claude" in session.providers_used
    assert session.provider_metadata["requested_model"] == "xai/grok-4-1-fast-reasoning"
    assert session.provider_metadata["effective_model"] == "claude-haiku-4-5"
    assert session.provider_metadata["fallback_used"] is True
    assert session.provider_metadata["fallback_reason"] == "TimeoutError: primary timed out"
