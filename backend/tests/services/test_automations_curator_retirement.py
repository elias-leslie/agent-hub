"""Legacy import cannot revive retired schedules and prunes ones removed from code."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import AutomationDefinition, AutomationProfile
from app.services import automations


@pytest.mark.asyncio
async def test_legacy_import_does_not_recreate_persona_job_automations() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    db.execute.return_value = empty
    db.get.return_value = None

    with patch.object(automations, "SCHEDULE_DEFINITIONS", ()):
        await automations.import_agent_hub_legacy(db)

    rows = [call.args[0] for call in db.add.call_args_list]
    assert not any(
        isinstance(row, AutomationDefinition) and row.workflow_key == "agent-hub.persona_job"
        for row in rows
    )
    assert not any(isinstance(row, AutomationProfile) for row in rows)
    # The static schedule-control and profile reads plus the retired-definition
    # lookup remain; no persona job reader.
    assert db.execute.await_count == 3


def _retirement_db(definitions: list[AutomationDefinition], in_flight: int) -> AsyncMock:
    db = AsyncMock()
    found = MagicMock()
    found.scalars.return_value.all.return_value = definitions
    db.execute.return_value = found
    db.scalar.return_value = in_flight
    return db


def _statements(db: AsyncMock) -> list[str]:
    return [str(call.args[0].compile(compile_kwargs={"literal_binds": True})) for call in db.execute.await_args_list]


@pytest.mark.asyncio
async def test_removed_agent_hub_schedule_is_deleted_with_its_profile_and_finished_runs() -> None:
    feedback = AutomationDefinition(workflow_key="agent-hub.feedback_cleanup", version=1, owner_project_id="agent-hub")
    db = _retirement_db([feedback], in_flight=0)

    retired = await automations.retire_removed_agent_hub_schedules(db)

    assert retired == ["agent-hub.feedback_cleanup"]
    lookup, *deletes = _statements(db)
    # Only Agent Hub's own Hatchet schedules that left the code are candidates.
    assert "owner_project_id = 'agent-hub'" in lookup
    assert "dispatch_kind = 'hatchet'" in lookup
    assert "'agent-hub.session_cleanup'" in lookup and "NOT IN" in lookup
    assert [statement.split()[2] for statement in deletes] == [
        "automation_runs", "automation_profiles", "automation_definitions",
    ]
    assert all("'agent-hub.feedback_cleanup'" in statement for statement in deletes)


@pytest.mark.asyncio
async def test_removed_agent_hub_schedule_with_a_run_in_flight_is_kept() -> None:
    feedback = AutomationDefinition(workflow_key="agent-hub.feedback_cleanup", version=1, owner_project_id="agent-hub")
    db = _retirement_db([feedback], in_flight=1)

    assert await automations.retire_removed_agent_hub_schedules(db) == []
    assert db.execute.await_count == 1
