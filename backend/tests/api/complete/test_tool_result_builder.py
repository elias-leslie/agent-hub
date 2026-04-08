from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.tool_result_builder import finalize_result


@pytest.mark.asyncio
async def test_finalize_result_tracks_citations_without_side_effect_commits() -> None:
    db = AsyncMock()

    with patch(
        "app.api.complete.tool_result_builder.track_citations",
        new_callable=AsyncMock,
        return_value=["mem-1"],
    ) as mock_track:
        result = await finalize_result(
            db=db,
            session_id="sess-1",
            model="claude-sonnet-4-6",
            provider="claude",
            content="Verified pulse and overlap state.",
            estimated_input_tokens=42,
            loaded_memory_uuids=["mem-1"],
            memory_group_id="grp-1",
            thinking_content="reasoning",
            thinking_tokens=12,
            turn=2,
            tool_calls_count=3,
            finish_reason="max_turns",
            progress_log=[],
            fallback_used=True,
            fallback_reason="tool_closeout_recovery_error",
        )

    mock_track.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert result.cited_uuids == ["mem-1"]
    assert result.input_tokens == 42
    assert result.output_tokens == len("Verified pulse and overlap state.") // 4
    assert result.finish_reason == "max_turns"
    assert result.fallback_used is True
