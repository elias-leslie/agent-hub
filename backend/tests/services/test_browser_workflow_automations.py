"""Immutable admission and cancel-newest overlap safety (e.g. browser handoffs)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.automations import admit_run


@pytest.mark.asyncio
@pytest.mark.parametrize("active, expected", [(0, "admitted"), (1, "rejected")])
async def test_browser_admission_serializes_overlapping_human_waits(active, expected):
    config = {"workflow": {"schema_version": 1, "steps": [{"id": "read"}]}, "parameters": {"name": "original"}}
    profile = SimpleNamespace(
        id="profile-1", workflow_key="summitflow/browser_workflow", project_id="summitflow",
        definition_version=1, enabled=False, owner_gate_reasons=[], revision=2, config=config,
        clock_owner="central",
    )
    definition = SimpleNamespace(
        manual_when_disabled=True, manual_advances_cursor=False, overlap_strategy="cancel_newest",
        dispatch_target="/automations/dispatch/browser_workflow",
    )
    policy = SimpleNamespace(project_id="summitflow", enabled=True, config={}, revision=1, sync_revision=1)
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = definition
    db.scalar.return_value = active
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=value))
        for value in (profile, None, policy)
    ]
    with patch("app.services.automations.live_owner_gate_reasons", new_callable=AsyncMock, return_value=[]):
        run = await admit_run(db, profile.id, trigger="manual", idempotency_key="stable")
    assert run.status == expected
    assert run.occurrence_key == "manual:profile-1:stable"
    assert run.config_snapshot == config
    assert run.config_snapshot is not config
    assert run.gate_reasons == (["profile_overlap_cancel_newest"] if active else [])
    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])


@pytest.mark.asyncio
async def test_retry_returns_existing_occurrence_before_overlap_or_policy_checks():
    db = AsyncMock()
    profile = SimpleNamespace(id="profile-1")
    existing = SimpleNamespace(id="same-run", status="accepted")
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=value))
        for value in (profile, existing)
    ]
    assert await admit_run(db, profile.id, trigger="manual", idempotency_key="stable") is existing
    db.get.assert_not_awaited()
    db.scalar.assert_not_awaited()
