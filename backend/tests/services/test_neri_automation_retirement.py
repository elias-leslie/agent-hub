"""Generic automation import cannot recreate Neri's retired notification product."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import AutomationDefinition, AutomationProfile, AutomationProjectPolicy
from app.services import automations


@pytest.mark.asyncio
async def test_legacy_import_registers_generic_definitions_but_no_neri_automation() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    empty = MagicMock()
    empty.scalars.return_value.all.return_value = []
    empty.scalar_one_or_none.return_value = None
    db.execute.return_value = empty
    db.get.return_value = None
    with (
        patch.object(automations, "SCHEDULE_DEFINITIONS", ()),
    ):
        await automations.import_agent_hub_legacy(db)
        await automations.import_agent_hub_legacy(db)

    rows = [call.args[0] for call in db.add.call_args_list]
    definitions = [row for row in rows if isinstance(row, AutomationDefinition)]
    assert any(row.workflow_key == "portfolio-ai/retrain_ml" for row in definitions)
    assert any(row.workflow_key == "summitflow/work_pickup" for row in definitions)
    assert all(row.owner_project_id != "neri" for row in definitions)
    assert not any(isinstance(row, AutomationProfile) and row.project_id == "neri" for row in rows)
    assert not any(isinstance(row, AutomationProjectPolicy) and row.project_id == "neri" for row in rows)
    assert not any(project == "neri" for _, project, *_ in automations.EXTERNAL_WORKFLOWS)


def test_generic_external_config_does_not_accept_retired_notification_settings() -> None:
    # Unknown keys use the ordinary closed schema, not a retired Neri special case.
    assert automations.external_config_schema("neri/notification_maintenance") == {
        "type": "object", "additionalProperties": False,
    }
    assert "workflow" in automations.external_config_schema("summitflow/browser_workflow")["required"]


@pytest.mark.asyncio
async def test_removed_definition_uses_generic_missing_definition_failure() -> None:
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    with pytest.raises(KeyError, match="notification_maintenance"):
        await automations.get_definition(db, "neri/notification_maintenance")
