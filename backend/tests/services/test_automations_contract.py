"""Behavior at the canonical automation admission and validation seam."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.automations import ProfileCreate, ProfileImport
from app.services.automations import (
    OWNER_POLICY_KEYS,
    AutomationValidationError,
    DefinitionRegistration,
    create_profile,
    effective_gate_reasons,
    ensure_future_one_time,
    occurrence_key,
    policy_sync_pending,
    register_definition,
    update_policy,
    validate_profile_payload,
)

_CAPS = {
    "screening_cap": {"type": "integer", "minimum": 0},
    "classification_cap": {"type": "integer", "minimum": 0},
}


def _registration_db(existing=None, policy=None):
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = policy
    return db, patch(
        "app.services.automations.get_definition", new_callable=AsyncMock,
        side_effect=KeyError("missing") if existing is None else None, return_value=existing,
    )


@pytest.mark.asyncio
async def test_owner_registration_creates_definition_with_fixed_route_and_owner_keys():
    db, get_definition = _registration_db()
    with get_definition:
        row = await register_definition(db, "jobinator-4000", "nightly_screen", DefinitionRegistration(
            label="Nightly screen", overlap_strategy="group_round_robin", policy_properties=_CAPS,
            default_schedule={"type": "cron", "value": "30 7 * * *", "timezone": "UTC"},
        ))
    assert row.workflow_key == "jobinator-4000/nightly_screen"
    assert row.dispatch_kind == "callback"
    assert row.dispatch_target == "/automations/dispatch/nightly_screen"
    assert row.policy_schema[OWNER_POLICY_KEYS] == ["classification_cap", "screening_cap"]
    assert row.policy_schema["required"] == ["classification_cap", "screening_cap"]
    assert "daily_limit" in row.policy_schema["properties"]
    # The owner's project gets a policy row so the shared limits can be edited.
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(getattr(item, "project_id", None) == "jobinator-4000" for item in added)


@pytest.mark.asyncio
async def test_owner_registration_updates_existing_definition_in_place():
    existing = SimpleNamespace(
        workflow_key="portfolio-ai/jenny_weekly_price_check", owner_project_id="portfolio-ai", version=1,
        label="old", default_schedule={},
    )
    db, get_definition = _registration_db(existing, policy=SimpleNamespace())
    with get_definition:
        row = await register_definition(db, "portfolio-ai", "jenny_weekly_price_check", DefinitionRegistration(
            label="Weekly price check", manual_when_disabled=True,
            default_schedule={"type": "cron", "value": "30 13 * * 6", "timezone": "UTC"},
        ))
    assert row is existing
    assert row.version == 1
    assert row.label == "Weekly price check"
    assert row.default_schedule["value"] == "30 13 * * 6"
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name, registration, match", [
    ("../other", DefinitionRegistration(label="x"), "workflow name"),
    ("ok", DefinitionRegistration(label="x", overlap_strategy="parallel"), "overlap_strategy"),
    ("ok", DefinitionRegistration(label="x", config_schema={"type": "nope"}), "config_schema"),
    ("ok", DefinitionRegistration(label="x", policy_properties={"daily_limit": {"type": "string"}}), "redefine"),
    ("ok", DefinitionRegistration(label="x", default_schedule={"type": "cron", "value": "not a cron"}), ""),
])
async def test_owner_registration_rejects_unsafe_or_invalid_declarations(name, registration, match):
    db, get_definition = _registration_db()
    with get_definition, pytest.raises(AutomationValidationError, match=match):
        await register_definition(db, "portfolio-ai", name, registration)
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_agent_hub_schedules_cannot_be_registered_as_callbacks():
    db, get_definition = _registration_db()
    with get_definition, pytest.raises(AutomationValidationError, match="not registered"):
        await register_definition(db, "agent-hub", "session_cleanup", DefinitionRegistration(label="x"))


def test_policy_sync_is_pending_only_for_owner_keys_at_a_newer_revision():
    policy = SimpleNamespace(config={"screening_cap": 1, "classification_cap": 2}, revision=3, sync_revision=2)
    assert policy_sync_pending(policy, ["classification_cap", "screening_cap"])
    assert not policy_sync_pending(policy, [])
    assert not policy_sync_pending(SimpleNamespace(config={}, revision=3, sync_revision=2), ["screening_cap"])
    assert not policy_sync_pending(SimpleNamespace(**{**vars(policy), "sync_revision": 3}), ["screening_cap"])


@pytest.mark.asyncio
async def test_new_profile_defaults_disabled_even_when_definition_defaults_enabled():
    payload = ProfileCreate(
        project_id="portfolio-ai", workflow_key="portfolio-ai/jenny_weekly_price_check",
        schedule_type="every", schedule_value="900000",
    )
    assert payload.enabled is False
    with pytest.raises(ValueError):
        ProfileImport.model_validate({**payload.model_dump(), "source_ref": "owner:work"} | {"enabled": None})

    db = AsyncMock()
    db.add = MagicMock()
    definition = SimpleNamespace(
        workflow_key="portfolio-ai/jenny_weekly_price_check", owner_project_id="portfolio-ai",
        version=1, label="Weekly price check", default_enabled=True,
        config_schema={"type": "object"}, dispatch_target="/automations/dispatch/jenny_weekly_price_check",
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
        workflow_key="portfolio-ai/jenny_weekly_price_check", owner_project_id="portfolio-ai",
        version=1, label="Weekly price check", dispatch_target="/automations/dispatch/jenny_weekly_price_check",
        config_schema={"type": "object"},
    )
    payload = {
        "project_id": "portfolio-ai", "workflow_key": "portfolio-ai/jenny_weekly_price_check",
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


@pytest.mark.asyncio
async def test_policy_edit_keeps_every_owner_registered_key():
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=SimpleNamespace(
        project_id="jobinator-4000", revision=1, config={},
    )))
    definition = SimpleNamespace(policy_schema={
        "type": "object", "properties": _CAPS, OWNER_POLICY_KEYS: ["classification_cap", "screening_cap"],
    })
    with (
        patch("app.services.automations.current_definitions", new_callable=AsyncMock, return_value=[definition]),
        pytest.raises(AutomationValidationError, match="requires classification_cap, screening_cap"),
    ):
        await update_policy(
            db, "jobinator-4000", enabled=False, config={"screening_cap": 200},
            expected_revision=1, changed_by="test",
        )


@pytest.mark.asyncio
async def test_policy_edit_validates_owner_key_values_against_registered_schema():
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=SimpleNamespace(
        project_id="jobinator-4000", revision=1, config={},
    )))
    definition = SimpleNamespace(policy_schema={
        "type": "object", "properties": _CAPS, OWNER_POLICY_KEYS: ["classification_cap", "screening_cap"],
    })
    with (
        patch("app.services.automations.current_definitions", new_callable=AsyncMock, return_value=[definition]),
        pytest.raises(AutomationValidationError, match="config:"),
    ):
        await update_policy(
            db, "jobinator-4000", enabled=False, config={"screening_cap": -1, "classification_cap": 4},
            expected_revision=1, changed_by="test",
        )
