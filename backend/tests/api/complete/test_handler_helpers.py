"""Tests for completion handler helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.complete._session_helpers import update_session_metadata
from app.api.complete.handler_helpers import save_and_track
from app.api.complete.schemas import CompletionRequest, MessageInput, SourceMetadata


def test_completion_request_accepts_high_turn_budgets() -> None:
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hello")],
        project_id="test-project",
        max_turns=5000,
    )

    assert request.max_turns == 5000


def test_completion_request_rejects_non_positive_turn_budgets() -> None:
    with pytest.raises(ValidationError):
        CompletionRequest(
            messages=[MessageInput(role="user", content="hello")],
            project_id="test-project",
            max_turns=0,
        )


@pytest.mark.asyncio
async def test_save_and_track_uses_model_used_for_events_and_cost() -> None:
    """When fallback is used, persistence should attribute to model_used."""
    request = CompletionRequest(
        messages=[MessageInput(role="user", content="hello")],
        project_id="test-project",
        source_metadata=SourceMetadata(
            transport="web",
            surface="work_chats",
            pane_id="pane-1",
            source_client="agent-hub/work-chats",
        ),
    )
    result = SimpleNamespace(
        content="done",
        provider="claude",
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
        patch(
            "app.api.complete.handler_helpers.persist_execution_observability",
            new_callable=AsyncMock,
        ) as mock_observability,
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

    save_events_args = mock_save_events.await_args
    assert save_events_args is not None
    observability_args = mock_observability.await_args
    assert observability_args is not None
    log_tokens_args = mock_log_tokens.await_args
    assert log_tokens_args is not None
    cost_args = mock_cost.call_args
    assert cost_args is not None

    assert save_events_args.args[6] == "claude-haiku-4-5"
    assert save_events_args.kwargs["source_metadata"] == {
        "transport": "web",
        "surface": "work_chats",
        "pane_id": "pane-1",
        "source_client": "agent-hub/work-chats",
    }
    assert observability_args.kwargs["orchestration_path"] == "single_turn"
    assert observability_args.kwargs["requested_max_turns"] == 1
    assert observability_args.kwargs["provider"] == "claude"
    assert cost_args.args[2] == "claude-haiku-4-5"
    assert log_tokens_args.args[2] == "claude-haiku-4-5"
    assert session.model == "claude-haiku-4-5"
    assert session.provider == "claude"
    assert "claude-haiku-4-5" in session.models_used
    assert "claude" in session.providers_used
    assert session.provider_metadata["requested_model"] == "xai/grok-4-1-fast-reasoning"
    assert session.provider_metadata["effective_model"] == "claude-haiku-4-5"
    assert session.provider_metadata["fallback_used"] is True
    assert session.provider_metadata["fallback_reason"] == "TimeoutError: primary timed out"


@pytest.mark.asyncio
async def test_update_session_metadata_flushes_without_commit() -> None:
    db = AsyncMock()
    session = SimpleNamespace(
        provider="codex",
        model="codex/gpt-5.4",
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
        provider_metadata={},
        agent_slug=None,
    )

    await update_session_metadata(
        db=db,
        session=session,
        provider="claude",
        model="claude-sonnet-4-6",
        agent_slug="persona",
    )

    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert session.provider == "claude"
    assert session.model == "claude-sonnet-4-6"
    assert session.agent_slug == "persona"
    assert session.provider_metadata["requested_model"] == "claude-sonnet-4-6"
    assert session.provider_metadata["requested_provider"] == "claude"
    assert session.provider_metadata["effective_model"] == "claude-sonnet-4-6"
    assert session.provider_metadata["effective_provider"] == "claude"
    assert session.provider_metadata["fallback_used"] is False


@pytest.mark.asyncio
async def test_update_session_metadata_honors_explicit_requested_model() -> None:
    db = AsyncMock()
    session = SimpleNamespace(
        provider="codex",
        model="codex/gpt-5.4",
        models_used=["codex/gpt-5.4"],
        providers_used=["codex"],
        provider_metadata={},
        agent_slug="persona",
    )

    await update_session_metadata(
        db=db,
        session=session,
        provider="claude",
        model="claude-sonnet-4-6",
        agent_slug="persona",
        requested_model="claude-sonnet-4-6",
        requested_provider="claude",
    )

    assert session.provider_metadata["requested_model"] == "claude-sonnet-4-6"
    assert session.provider_metadata["requested_provider"] == "claude"
    assert session.provider_metadata["effective_model"] == "claude-sonnet-4-6"
    assert session.provider_metadata["effective_provider"] == "claude"
    assert session.provider_metadata["fallback_used"] is False
