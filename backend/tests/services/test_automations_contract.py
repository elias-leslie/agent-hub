"""Behavior at the canonical automation admission and validation seam."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.automations import ProfileCreate, ProfileImport
from app.services.automations import (
    AutomationValidationError,
    create_profile,
    effective_gate_reasons,
    occurrence_key,
    policy_profile_gate_reasons,
    policy_schema_for,
    update_policy,
    validate_policy_config,
    validate_profile_payload,
)


@pytest.mark.asyncio
async def test_new_profile_defaults_disabled_even_when_definition_defaults_enabled():
    payload = ProfileCreate(
        project_id="summitflow", workflow_key="summitflow/work_pickup",
        schedule_type="every", schedule_value="900000",
    )
    assert payload.enabled is False
    with pytest.raises(ValueError):
        ProfileImport.model_validate({**payload.model_dump(), "source_ref": "owner:work"} | {"enabled": None})

    db = AsyncMock()
    db.add = MagicMock()
    definition = SimpleNamespace(
        workflow_key="summitflow/work_pickup", owner_project_id="summitflow",
        version=1, label="Work pickup", default_enabled=True,
        config_schema={"type": "object"}, dispatch_target="/automations/dispatch/work_pickup",
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


def test_summitflow_owned_profile_can_target_another_project():
    definition = SimpleNamespace(
        owner_project_id="summitflow", workflow_key="summitflow/work_pickup",
        config_schema={"type": "object", "properties": {"batch_limit": {"type": "integer"}}},
    )
    value = validate_profile_payload({
        "project_id": "agent-hub", "workflow_key": "summitflow/work_pickup",
        "schedule_type": "every", "schedule_value": "1800000", "config": {"batch_limit": 5},
    }, definition)
    assert value["project_id"] == "agent-hub"


def test_summitflow_workflow_gates_do_not_disable_unrelated_project_routines():
    policy = SimpleNamespace(config={"autonomous_enabled": False, "routine_upkeep_enabled": True})
    assert policy_profile_gate_reasons("summitflow/work_pickup", policy) == ["autonomous_disabled"]
    assert policy_profile_gate_reasons("summitflow/task_generation", policy) == []
    assert policy_profile_gate_reasons("neri/notification_maintenance", policy) == []


def test_existing_summitflow_policy_values_keep_their_types():
    config = validate_policy_config({
        "autonomous_end_hour": 24,
        "autonomous_auto_merge_tiers": [1, 2],
        "autonomous_max_tasks_per_day": None,
        "quality_gate_tools": ["ruff", "types"],
    })
    assert config["autonomous_end_hour"] == 24
    assert config["autonomous_auto_merge_tiers"] == [1, 2]
    assert config["quality_gate_tools"] == ["ruff", "types"]
    assert "filters" not in config


def test_policy_catalog_only_shows_owner_specific_fields_for_its_project():
    assert "autonomous_max_concurrent" in policy_schema_for("summitflow")["properties"]
    assert "autonomous_max_concurrent" not in policy_schema_for("neri")["properties"]
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
