"""The central clock never records rejected runs for a disabled project."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import automation_dispatch
from app.services.automation_dispatch import dispatch_due


def _session(db):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _profile(project_id: str):
    return SimpleNamespace(
        id=f"profile-{project_id}", project_id=project_id,
        next_run_at=datetime.now(UTC) - timedelta(minutes=5),
        schedule_type="interval", schedule_value="3600", schedule_timezone="UTC",
    )


def _db_for(profile, policy):
    db = AsyncMock()

    async def get(model, key):
        return profile if model is automation_dispatch.AutomationProfile else policy

    db.get.side_effect = get
    return db


@pytest.mark.asyncio
async def test_disabled_project_advances_clock_without_run_row():
    profile = _profile("jobinator-4000")
    policy = SimpleNamespace(project_id="jobinator-4000", enabled=False, config={}, revision=1, sync_revision=1)
    ids_db = AsyncMock()
    ids_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[profile.id]))))
    work_db = _db_for(profile, policy)
    next_at = datetime.now(UTC) + timedelta(hours=1)

    with (
        patch.object(automation_dispatch, "async_session", side_effect=[_session(ids_db), _session(work_db)]),
        patch.object(automation_dispatch, "next_due", return_value=next_at) as next_due,
        patch.object(automation_dispatch, "admit_run", new=AsyncMock()) as admit,
        patch.object(automation_dispatch, "dispatch_run", new=AsyncMock()) as dispatch,
    ):
        assert await dispatch_due() == 0

    admit.assert_not_awaited()
    dispatch.assert_not_awaited()
    work_db.add.assert_not_called()
    assert profile.next_run_at == next_at
    assert next_due.call_args.args[:3] == ("interval", "3600", "UTC")
    assert next_due.call_args.args[3] > datetime.now(UTC) - timedelta(minutes=1)
    work_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_enabled_project_still_admits_scheduled_run():
    profile = _profile("summitflow")
    policy = SimpleNamespace(project_id="summitflow", enabled=True, config={}, revision=1, sync_revision=1)
    ids_db = AsyncMock()
    ids_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[profile.id]))))
    work_db = _db_for(profile, policy)
    run = SimpleNamespace(id="run-1", status="admitted")

    with (
        patch.object(automation_dispatch, "async_session", side_effect=[_session(ids_db), _session(work_db)]),
        patch.object(automation_dispatch, "admit_run", new=AsyncMock(return_value=run)) as admit,
        patch.object(automation_dispatch, "dispatch_run", new=AsyncMock()) as dispatch,
    ):
        assert await dispatch_due() == 1

    admit.assert_awaited_once()
    assert admit.call_args.kwargs["trigger"] == "scheduled"
    dispatch.assert_awaited_once_with("run-1")
