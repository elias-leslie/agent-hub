"""Session list and detail reads must not repeat their heaviest scans on every poll."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.services import ownership_inventory, session_accounting, session_responses


@pytest.fixture
def lanes(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    async def slow_ownership(_db, _project_id):
        await asyncio.sleep(0.05)
        return [SimpleNamespace(session_id="owner-1")]

    mocks = {
        "ownership": AsyncMock(side_effect=slow_ownership),
        "specialists": AsyncMock(return_value=[SimpleNamespace(session_id="spec-1")]),
    }
    monkeypatch.setattr(session_responses, "query_project_ownership", mocks["ownership"])
    monkeypatch.setattr(session_responses, "query_project_active_specialists", mocks["specialists"])
    return mocks


async def test_lane_ids_are_computed_once_for_concurrent_and_repeated_reads(lanes, monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_lane_cache_seconds", 60.0)
    results = await asyncio.gather(
        *(session_responses.build_project_lane_session_ids(None, {"p"}) for _ in range(8))
    )
    assert all(result == ({"owner-1"}, {"spec-1"}) for result in results)
    await session_responses.build_project_lane_session_ids(None, {"p"})
    assert lanes["ownership"].await_count == 1
    assert lanes["specialists"].await_count == 1


async def test_lane_ids_are_recomputed_when_the_cache_is_off(lanes, monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_lane_cache_seconds", 0.0)
    await session_responses.build_project_lane_session_ids(None, {"p"})
    await session_responses.build_project_lane_session_ids(None, {"p"})
    assert lanes["ownership"].await_count == 2


async def test_ownership_scope_work_runs_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def build(_sessions, _events):
        seen.append(threading.get_ident())
        return []

    monkeypatch.setattr(ownership_inventory, "_fetch_candidate_sessions", AsyncMock(return_value=[]))
    monkeypatch.setattr(ownership_inventory, "_fetch_scope_events", AsyncMock(return_value={}))
    monkeypatch.setattr(ownership_inventory, "_build_owners", build)
    await ownership_inventory.query_project_ownership(None, "p")
    assert seen and seen[0] != loop_thread


async def test_accounting_is_read_once_per_window_and_only_for_sessions_without_a_recent_result(monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_accounting_cache_seconds", 60)
    read = AsyncMock(side_effect=lambda _db, ids, **_: {sid: {"id": sid} for sid in ids if sid != "idle"})
    monkeypatch.setattr(session_accounting, "_read_session_accounting", read)
    end = datetime.now(UTC)
    window = {"start": end - timedelta(hours=24), "end": end}

    first = await session_accounting.fetch_session_accounting(None, ["a", "idle"], **window)
    again = await session_accounting.fetch_session_accounting(None, ["a", "idle"], **window)
    wider = await session_accounting.fetch_session_accounting(None, ["a", "b"], **window)

    assert first == again == {"a": {"id": "a"}}
    assert wider == {"a": {"id": "a"}, "b": {"id": "b"}}
    assert [call.args[1] for call in read.await_args_list] == [["a", "idle"], ["b"]]


async def test_accounting_subquery_is_never_cached(monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_accounting_cache_seconds", 60)
    read = AsyncMock(return_value={})
    monkeypatch.setattr(session_accounting, "_read_session_accounting", read)
    end = datetime.now(UTC)
    for _ in range(2):
        await session_accounting.fetch_session_accounting(None, object(), start=end - timedelta(hours=1), end=end)
    assert read.await_count == 2


def test_default_accounting_window_ends_on_a_bucket_boundary(monkeypatch) -> None:
    monkeypatch.setattr(settings, "session_accounting_cache_seconds", 30)
    start, end, _ = session_accounting.accounting_window(None, None, None)
    assert end.timestamp() % 30 == 0
    assert end - start == timedelta(hours=24)
    monkeypatch.setattr(settings, "session_accounting_cache_seconds", 0)
    _, exact, _ = session_accounting.accounting_window(None, None, None)
    assert abs((datetime.now(UTC) - exact).total_seconds()) < 5
