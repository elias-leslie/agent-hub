"""The analytics tier-changes card reads tier moves from memory revisions (tier_change_log is frozen)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.services.memory import _analytics_top
from app.services.memory.tier_operations import TIER_ACTOR

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _fake_session(monkeypatch: pytest.MonkeyPatch, summary: list, recent: list) -> list:
    """Stand-in for async_session returning canned rows; records (sql, params) per execute."""
    calls: list = []

    class Session:
        async def execute(self, statement, params):
            sql = str(statement)
            calls.append((sql, params))
            return MagicMock(all=lambda: summary if "GROUP BY" in sql else recent)

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(_analytics_top, "async_session", session)
    return calls


@pytest.mark.asyncio
async def test_card_returns_tier_moves_recorded_as_revisions(monkeypatch):
    summary = [SimpleNamespace(change_type="demotion", cnt=2, latest=NOW),
               SimpleNamespace(change_type="promotion", cnt=1, latest=NOW - timedelta(days=1))]
    recent = [SimpleNamespace(memory_uuid="0b0e3c1a-0000-0000-0000-000000000000", prev_tier=2, tier=3,
                              prev_score=0.4, lifecycle_score=0.1, change_type="demotion", created_at=NOW),
              SimpleNamespace(memory_uuid="1c1f4d2b-0000-0000-0000-000000000000", prev_tier=None, tier=3,
                              prev_score=None, lifecycle_score=None, change_type="tier_move", created_at=NOW)]
    calls = _fake_session(monkeypatch, summary, recent)

    result = cast(Any, await _analytics_top.get_tier_changes_summary(lookback_delta=timedelta(days=7)))

    for sql, params in calls:
        assert "memory_revisions" in sql and "tier_change_log" not in sql
        assert params["actor"] == TIER_ACTOR
    assert result["total"] == 3
    assert result["by_type"]["demotion"] == {"count": 2, "latest": NOW.isoformat()}
    assert result["recent"][0] == {
        "episode_uuid": "0b0e3c1a-0000-0000-0000-000000000000", "old_tier": "guardrail", "new_tier": "reference",
        "change_type": "demotion", "lifecycle_score_before": 0.4, "lifecycle_score_after": 0.1,
        "created_at": NOW.isoformat()}
    # A move whose earlier revision was never stored says so; it does not invent a source tier.
    assert result["recent"][1]["old_tier"] is None


@pytest.mark.asyncio
async def test_no_moves_is_an_honest_empty_summary(monkeypatch):
    _fake_session(monkeypatch, [], [])

    assert await _analytics_top.get_tier_changes_summary(days=30) == {"by_type": {}, "recent": [], "total": 0}
