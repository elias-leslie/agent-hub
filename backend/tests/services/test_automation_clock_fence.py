"""A transferred static schedule has exactly one accepted clock."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.workflow_schedule_registry import is_workflow_schedule_enabled


@pytest.mark.asyncio
async def test_legacy_cron_tick_is_rejected_after_transfer():
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=SimpleNamespace(id="profile-1", clock_owner="central"))
    )
    assert await is_workflow_schedule_enabled("session_cleanup", db) is False
    db.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_run_admitted_for_transferred_profile_can_execute():
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=SimpleNamespace(id="profile-1", clock_owner="central"))
    )
    db.get.return_value = SimpleNamespace(profile_id="profile-1", status="accepted")
    assert await is_workflow_schedule_enabled(
        "session_cleanup", db, automation_run_id="run-1"
    ) is True
    db.get.return_value = SimpleNamespace(profile_id="other-profile", status="accepted")
    assert await is_workflow_schedule_enabled(
        "session_cleanup", db, automation_run_id="run-1"
    ) is False


@pytest.mark.asyncio
async def test_explicit_manual_run_can_execute_while_legacy_toggle_is_off():
    db = AsyncMock()
    db.execute.return_value = MagicMock(
        scalar_one_or_none=MagicMock(return_value=SimpleNamespace(id="profile-1", clock_owner="legacy"))
    )
    db.get.return_value = SimpleNamespace(profile_id="profile-1", status="accepted", trigger="manual")
    assert await is_workflow_schedule_enabled(
        "session_cleanup", db, automation_run_id="run-1"
    ) is True
