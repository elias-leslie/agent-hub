"""Tests for agentic completion result finalization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.complete.result_finalizer import finalize_completion_result


@pytest.mark.asyncio
async def test_finalize_completion_result_tracks_effective_model_and_fallback_reason() -> None:
    db = AsyncMock()
    session = SimpleNamespace(
        status="active",
        session_type="completion",
        provider="claude",
        model="claude-sonnet-4-6",
        models_used=["claude-sonnet-4-6"],
        providers_used=["claude"],
        provider_metadata={},
    )

    with (
        patch("app.api.complete.result_finalizer.log_token_usage", new_callable=AsyncMock) as mock_log_tokens,
        patch("app.api.complete.result_finalizer.publish_complete", new_callable=AsyncMock),
        patch("app.api.complete.result_finalizer.estimate_cost", return_value=MagicMock(total_cost_usd=0.0)),
    ):
        await finalize_completion_result(
            db=db,
            session=session,
            session_id="sess-1",
            requested_model="claude-sonnet-4-6",
            effective_model="codex/gpt-5.4",
            total_input_tokens=10,
            total_output_tokens=20,
            is_new_session=True,
            final_result=None,
            fallback_used=True,
            fallback_reason="TimeoutError: claude primary timed out",
        )

    assert session.model == "codex/gpt-5.4"
    assert session.provider == "codex"
    assert session.status == "completed"
    assert session.provider_metadata["requested_model"] == "claude-sonnet-4-6"
    assert session.provider_metadata["effective_model"] == "codex/gpt-5.4"
    assert session.provider_metadata["fallback_used"] is True
    assert session.provider_metadata["fallback_reason"] == "TimeoutError: claude primary timed out"
    assert mock_log_tokens.await_args.args[2] == "codex/gpt-5.4"
