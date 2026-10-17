"""Legacy import cannot revive retired persona job or memory review schedules."""

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
    # Only the static schedule-control and profile reads remain; no persona job reader.
    assert db.execute.await_count == 2
