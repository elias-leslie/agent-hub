"""The clock settles owner receipts after its short database sessions close."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import AutomationDefinition, AutomationProfile
from app.services.automation_dispatch import dispatch_run, reconcile_runs


class BoundDefinition:
    def __init__(self) -> None:
        self.bound = True

    @property
    def dispatch_kind(self) -> str:
        if not self.bound:
            raise RuntimeError("definition was read after its session closed")
        return "hatchet"

    @property
    def dispatch_target(self) -> str:
        if not self.bound:
            raise RuntimeError("definition was read after its session closed")
        return "session_cleanup"

    @property
    def owner_project_id(self) -> str:
        if not self.bound:
            raise RuntimeError("definition was read after its session closed")
        return "agent-hub"


class Session:
    def __init__(self, *, item=None, pending=None) -> None:
        self.item = item
        self.pending = pending or []
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        if isinstance(self.item, BoundDefinition):
            self.item.bound = False

    async def execute(self, _query):
        return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=self.pending))))

    async def get(self, model, key):
        return self.item


class DispatchSession(Session):
    def __init__(self, *, run, definition=None, profile=None) -> None:
        super().__init__(item=definition or run)
        self.run = run
        self.definition = definition
        self.profile = profile

    async def __aexit__(self, *_args):
        if self.definition is not None:
            self.definition.bound = False

    async def execute(self, _query):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=self.run))

    async def get(self, model, key):
        if model is AutomationDefinition:
            return self.definition
        if model is AutomationProfile:
            return self.profile
        return self.run


@pytest.mark.asyncio
async def test_reconcile_snapshots_definition_before_session_closes():
    pending = SimpleNamespace(
        id="run-1", status="accepted", owner_run_id="hatchet-1",
        workflow_key="agent-hub.session_cleanup", definition_version=1,
    )
    run = SimpleNamespace(status="accepted", completed_at=None)
    sessions = [Session(pending=[pending]), Session(item=BoundDefinition()), Session(item=run)]
    hatchet = SimpleNamespace(runs=SimpleNamespace(aio_get_status=AsyncMock(return_value=SimpleNamespace(value="COMPLETED"))))

    with (
        patch("app.services.automation_dispatch.async_session", side_effect=sessions),
        patch("app.hatchet_app.get_hatchet", return_value=hatchet),
    ):
        settled = await reconcile_runs()

    assert settled == 1
    assert run.status == "succeeded"
    assert run.completed_at is not None
    sessions[2].commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_snapshots_owner_definition_before_session_closes():
    run = SimpleNamespace(
        id="run-1", profile_id="profile-1", workflow_key="agent-hub.session_cleanup",
        definition_version=1, profile_revision=2, status="admitted",
        occurrence_key="scheduled:profile-1:2026-09-23T16:30:00Z", trigger="scheduled",
        scheduled_for=datetime(2026, 9, 23, 16, 30, tzinfo=UTC),
        created_at=datetime(2026, 9, 23, 16, 30, tzinfo=UTC),
        config_snapshot={}, policy_snapshot={}, owner_run_id=None, owner_receipt=None,
        accepted_at=None, completed_at=None, error=None,
    )
    sessions = [
        DispatchSession(run=run, definition=BoundDefinition(), profile=SimpleNamespace(project_id="agent-hub")),
        DispatchSession(run=run),
    ]
    task = SimpleNamespace(aio_run_no_wait=AsyncMock(return_value=SimpleNamespace(workflow_run_id="hatchet-1")))

    with (
        patch("app.services.automation_dispatch.async_session", side_effect=sessions),
        patch("app.services.automation_dispatch._hatchet_task", return_value=task),
    ):
        await dispatch_run(run.id)

    assert run.status == "accepted"
    assert run.owner_run_id == "hatchet-1"
    sessions[1].commit.assert_awaited_once()
