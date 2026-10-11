"""Behavior at the canonical automation admission and validation seam."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.automations import ProfileCreate, ProfileImport
from app.services.automations import (
    EXTERNAL_WORKFLOWS,
    AutomationValidationError,
    create_profile,
    effective_gate_reasons,
    ensure_future_one_time,
    occurrence_key,
    policy_schema_for,
    update_policy,
    validate_profile_payload,
)


def test_portfolio_weekly_learning_has_a_canonical_schedule_definition():
    matches = [row for row in EXTERNAL_WORKFLOWS if row[0] == "portfolio-ai/jenny_weekly_learning"]
    assert len(matches) == 1
    assert matches[0][1] == "portfolio-ai"
    assert matches[0][4] == {"type": "cron", "value": "0 14 * * 6", "timezone": "UTC"}


@pytest.mark.asyncio
async def test_new_profile_defaults_disabled_even_when_definition_defaults_enabled():
    payload = ProfileCreate(
        project_id="portfolio-ai", workflow_key="portfolio-ai/retrain_ml",
        schedule_type="every", schedule_value="900000",
    )
    assert payload.enabled is False
    with pytest.raises(ValueError):
        ProfileImport.model_validate({**payload.model_dump(), "source_ref": "owner:work"} | {"enabled": None})

    db = AsyncMock()
    db.add = MagicMock()
    definition = SimpleNamespace(
        workflow_key="portfolio-ai/retrain_ml", owner_project_id="portfolio-ai",
        version=1, label="Retrain ML", default_enabled=True,
        config_schema={"type": "object"}, dispatch_target="/automations/dispatch/retrain_ml",
    )
    with patch("app.services.automations.get_definition", new_callable=AsyncMock, return_value=definition):
        profile = await create_profile(db, payload.model_dump(exclude={"enabled"}), changed_by="test")
    assert profile.enabled is False


def test_shared_project_policy_blocks_all_profiles():
    reasons = effective_gate_reasons(
        profile_enabled=True,
        policy_enabled=False,
        owner_gate_reasons=[],
        manual=False,
        manual_when_disabled=False,
    )
    assert reasons == ["project_disabled"]


def test_manual_action_can_bypass_background_toggle_only_when_registered():
    assert effective_gate_reasons(
        profile_enabled=False,
        policy_enabled=True,
        owner_gate_reasons=[],
        manual=True,
        manual_when_disabled=True,
    ) == []
    assert effective_gate_reasons(
        profile_enabled=False,
        policy_enabled=False,
        owner_gate_reasons=[],
        manual=True,
        manual_when_disabled=True,
    ) == ["project_disabled"]


def test_occurrence_key_is_stable_for_retry_and_distinct_for_next_tick():
    due = datetime(2026, 9, 23, 14, 0, tzinfo=UTC)
    assert occurrence_key("profile-1", due) == occurrence_key("profile-1", due)
    assert occurrence_key("profile-1", due) != occurrence_key("profile-1", datetime(2026, 9, 23, 14, 1, tzinfo=UTC))


def test_invalid_schedule_is_rejected_before_write():
    with pytest.raises(AutomationValidationError, match="schedule_value"):
        validate_profile_payload({
            "project_id": "agent-hub",
            "workflow_key": "agent-hub.session_cleanup",
            "schedule_type": "cron",
            "schedule_value": "bad cron",
            "schedule_timezone": "UTC",
        })


def test_new_one_time_schedule_must_be_in_future_with_named_timezone():
    now = datetime(2026, 9, 23, 18, 0, tzinfo=UTC)
    with pytest.raises(AutomationValidationError, match="future"):
        ensure_future_one_time({
            "schedule_type": "at", "schedule_value": "2026-09-23T14:00:00",
            "schedule_timezone": "America/New_York",
        }, now)
    ensure_future_one_time({
        "schedule_type": "at", "schedule_value": "2026-09-23T14:01:00",
        "schedule_timezone": "America/New_York",
    }, now)
    ensure_future_one_time({
        "schedule_type": "at", "schedule_value": "2026-09-23T19:00:00+00:00",
        "schedule_timezone": "UTC",
    }, now)


@pytest.mark.asyncio
async def test_create_profile_rejects_past_one_time_before_adding_owner_or_profile():
    db = AsyncMock()
    db.add = MagicMock()
    definition = SimpleNamespace(
        workflow_key="portfolio-ai/retrain_ml", owner_project_id="portfolio-ai",
        version=1, label="Retrain ML", dispatch_target="/automations/dispatch/retrain_ml",
        config_schema={"type": "object"},
    )
    payload = {
        "project_id": "portfolio-ai", "workflow_key": "portfolio-ai/retrain_ml",
        "schedule_type": "at", "schedule_value": "2026-03-05T12:00:00Z",
    }
    with (
        patch("app.services.automations.get_definition", new_callable=AsyncMock, return_value=definition),
        pytest.raises(AutomationValidationError, match="future"),
    ):
        await create_profile(db, payload, changed_by="test")
    db.add.assert_not_called()


def test_summitflow_owned_profile_can_target_another_project():
    definition = SimpleNamespace(
        owner_project_id="summitflow", workflow_key="summitflow/browser_workflow",
        config_schema={"type": "object", "properties": {"batch_limit": {"type": "integer"}}},
    )
    value = validate_profile_payload({
        "project_id": "agent-hub", "workflow_key": "summitflow/browser_workflow",
        "schedule_type": "every", "schedule_value": "1800000", "config": {"batch_limit": 5},
    }, definition)
    assert value["project_id"] == "agent-hub"


def test_retired_summitflow_policy_keys_are_not_in_the_catalog():
    for project in ("summitflow", "agent-hub", "portfolio-ai"):
        properties = policy_schema_for(project)["properties"]
        assert not any(key.startswith(("autonomous_", "quality_gate_")) for key in properties)
        assert "routine_upkeep_enabled" not in properties


def test_policy_catalog_only_shows_owner_specific_fields_for_its_project():
    assert "daily_limit" in policy_schema_for("neri")["properties"]
    assert "screening_cap" in policy_schema_for("jobinator-4000")["properties"]
    assert "classification_cap" in policy_schema_for("jobinator-4000")["properties"]
    assert "screening_cap" not in policy_schema_for("neri")["properties"]


@pytest.mark.asyncio
async def test_jobinator_policy_keeps_both_shared_quota_limits():
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=SimpleNamespace(
        project_id="jobinator-4000", revision=1, config={},
    )))
    with pytest.raises(AutomationValidationError, match="screening_cap and classification_cap"):
        await update_policy(
            db, "jobinator-4000", enabled=False, config={"screening_cap": 200},
            expected_revision=1, changed_by="test",
        )
