"""Tests for memory injection metrics updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory.metrics_collector_helpers import _apply_citation_updates


@pytest.mark.asyncio
async def test_apply_citation_updates_tracks_selected_reference_citations() -> None:
    session = AsyncMock()
    selected_result = MagicMock()
    selected_result.scalar_one_or_none.return_value = [
        "ref-1",
        "ref-2",
        "ref-3",
    ]
    session.execute.side_effect = [selected_result, MagicMock()]

    updated = await _apply_citation_updates(
        session=session,
        record_id=17,
        memories_cited=["ref-2", "mandate-1", "ref-3"],
        task_succeeded=True,
    )

    assert updated == 1
    update_stmt = session.execute.await_args_list[1].args[0]
    compiled = update_stmt.compile().params
    assert compiled["reference_cited_count"] == 2
    assert compiled["memories_cited"] == ["ref-2", "mandate-1", "ref-3"]
    assert compiled["task_succeeded"] is True
    session.commit.assert_awaited_once()
