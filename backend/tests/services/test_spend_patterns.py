"""Spend patterns keep the other sections when one query fails."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services import spend_patterns


@pytest.mark.asyncio
async def test_failing_section_is_listed_unavailable(monkeypatch) -> None:
    ok = AsyncMock(return_value={"ok": True})
    for name in ("_unpriced", "_effort", "_model_names", "_empty_sessions", "_gated_automations"):
        monkeypatch.setattr(spend_patterns, name, ok)
    monkeypatch.setattr(spend_patterns, "_repeated_calls", AsyncMock(side_effect=RuntimeError("bad sql")))
    monkeypatch.setattr(spend_patterns, "_weekly_spike", AsyncMock(return_value={"spike": False}))
    db = AsyncMock()

    result = await spend_patterns.build_spend_patterns(db, days=7)

    assert result["unavailable"] == ["repeated_calls"]
    assert result["repeated_calls"] is None
    assert result["unpriced"] == {"ok": True}
    assert result["weekly_spike"] == {"spike": False}
    db.rollback.assert_awaited_once()
