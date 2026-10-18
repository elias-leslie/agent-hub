"""Session close settings drive the reaper and live classification."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import session_close_settings
from app.services.session_close_settings import SessionCloseThresholds
from app.workflows.session_reaper import reap_stale_sessions


@pytest.fixture(autouse=True)
def restore_defaults(monkeypatch):
    monkeypatch.setattr(session_close_settings, "_current", SessionCloseThresholds())


def test_defaults_match_former_hardcoded_values() -> None:
    values = session_close_settings.current()
    assert values.dead_candidate_after_seconds == 30 * 60
    assert values.reapable_after_seconds == 6 * 60 * 60
    assert values.zero_event_close_after_seconds == 60 * 60
    assert values.transcript_sync_close_after_seconds == 60 * 60
    assert values.completion_close_after_minutes == 240
    assert values.any_session_close_after_minutes == 1440


def test_validation_refuses_close_before_dead() -> None:
    with pytest.raises(ValueError):
        session_close_settings.validate(SessionCloseThresholds(dead_candidate_after_minutes=120, reapable_after_minutes=60))
    with pytest.raises(ValueError):
        session_close_settings.validate(SessionCloseThresholds(completion_close_after_minutes=600, any_session_close_after_minutes=300))


@pytest.mark.asyncio
async def test_update_refuses_unknown_fields() -> None:
    with pytest.raises(ValueError, match="Unknown settings"):
        await session_close_settings.update(AsyncMock(), {"bogus": 1}, updated_by="test")


@pytest.mark.asyncio
async def test_reaper_uses_configured_thresholds_in_summaries() -> None:
    db = AsyncMock()
    completion = MagicMock(id="c", status="active", request_source=None, provider_metadata={})
    stale = MagicMock(id="s", status="active", request_source=None, provider_metadata={})
    results = []
    for rows in ([completion], [], [stale]):
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        results.append(result)
    db.execute.side_effect = results
    thresholds = SessionCloseThresholds(completion_close_after_minutes=90, any_session_close_after_minutes=2880)

    await reap_stale_sessions(db, datetime.now(UTC), thresholds)

    assert completion.provider_metadata["live_activity"]["summary"] == "Auto-completed by session reaper after 90m inactivity"
    assert stale.provider_metadata["live_activity"]["summary"] == "Auto-completed by session reaper after 48h inactivity"


def test_live_classification_reads_the_current_settings(monkeypatch) -> None:
    from app.services._session_lifecycle import _should_reap

    signals = ["heartbeat_only"]
    assert not _should_reap(signals, [], 2 * 60 * 60, False)
    monkeypatch.setattr(session_close_settings, "_current", SessionCloseThresholds(reapable_after_minutes=60))
    assert _should_reap(signals, [], 2 * 60 * 60, False)
