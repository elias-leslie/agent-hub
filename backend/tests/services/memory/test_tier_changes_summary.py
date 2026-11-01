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
                              lifecycle_score=0.1, change_type="demotion", created_at=NOW),
              SimpleNamespace(memory_uuid="1c1f4d2b-0000-0000-0000-000000000000", prev_tier=None, tier=3,
                              lifecycle_score=None, change_type="tier_move", created_at=NOW)]
    calls = _fake_session(monkeypatch, summary, recent)

    result = cast(Any, await _analytics_top.get_tier_changes_summary(lookback_delta=timedelta(days=7)))

    for sql, params in calls:
        assert "memory_revisions" in sql and "tier_change_log" not in sql
        assert params["actor"] == TIER_ACTOR
    assert result["total"] == 3
    assert result["by_type"]["demotion"] == {"count": 2, "latest": NOW.isoformat()}
    assert result["recent"][0] == {
        "episode_uuid": "0b0e3c1a-0000-0000-0000-000000000000", "old_tier": "guardrail", "new_tier": "reference",
        "change_type": "demotion", "lifecycle_score": 0.1,
        "created_at": NOW.isoformat()}
    # A move whose earlier revision was never stored says so; it does not invent a source tier.
    assert result["recent"][1]["old_tier"] is None


@pytest.mark.asyncio
async def test_no_moves_is_an_honest_empty_summary(monkeypatch):
    _fake_session(monkeypatch, [], [])

    assert await _analytics_top.get_tier_changes_summary(days=30) == {"by_type": {}, "recent": [], "total": 0}


@pytest.mark.asyncio
async def test_card_gives_only_the_moves_own_score_never_a_before_score(monkeypatch):
    """Scores change without revisions, so the previous revision's score can be months stale."""
    recent = [SimpleNamespace(memory_uuid="2d2a5e3c-0000-0000-0000-000000000000", prev_tier=3, tier=4,
                              lifecycle_score=0.12, change_type="demotion", created_at=NOW)]
    calls = _fake_session(monkeypatch, [], recent)

    result = cast(Any, await _analytics_top.get_tier_changes_summary(days=30))

    (move,) = result["recent"]
    assert move["lifecycle_score"] == 0.12
    assert not [key for key in move if "before" in key or "after" in key]
    for sql, _ in calls:
        assert "LAG(lifecycle_score)" not in sql and "prev_score" not in sql


@pytest.mark.asyncio
async def test_card_tells_self_heals_from_other_promotions(monkeypatch):
    summary = [SimpleNamespace(change_type="self_heal", cnt=1, latest=NOW)]
    calls = _fake_session(monkeypatch, summary, [])

    result = cast(Any, await _analytics_top.get_tier_changes_summary(days=30))

    assert result["by_type"]["self_heal"]["count"] == 1
    # self_heal.py writes the reason "self-heal: ..." on the optimizer's revision.
    assert all("change_reason LIKE 'self-heal:%'" in sql and "'self_heal'" in sql for sql, _ in calls)
