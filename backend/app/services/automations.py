"""Canonical automation admission, validation, and legacy-state import."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from jsonschema import ValidationError as JsonSchemaError
from jsonschema import validate as validate_json
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AutomationDefinition,
    AutomationProfile,
    AutomationProfileRevision,
    AutomationProjectPolicy,
    AutomationRun,
    WorkflowScheduleControl,
)
from app.services.workflow_schedule_registry import SCHEDULE_DEFINITIONS

logger = logging.getLogger(__name__)

# Deployment-owned callback routes. Origins come only from the registered project's
# local .index.yaml; callers cannot supply an execution URL through a profile.
EXTERNAL_WORKFLOWS: tuple[tuple[str, str, str, str, dict], ...] = (
    ("summitflow/browser_workflow", "summitflow", "Browser workflow", "cancel_newest", {}),
    ("portfolio-ai/jenny_daily_household_maintenance", "portfolio-ai", "Daily household maintenance", "cancel_in_progress", {"type": "cron", "value": "15 13 * * *", "timezone": "UTC"}),
    ("portfolio-ai/jenny_daily_operator", "portfolio-ai", "Daily operator", "cancel_in_progress", {"type": "cron", "value": "15 22 * * 1-5", "timezone": "UTC"}),
    ("portfolio-ai/jenny_weekly_learning", "portfolio-ai", "Weekly learning", "cancel_in_progress", {"type": "cron", "value": "0 14 * * 6", "timezone": "UTC"}),
    ("portfolio-ai/retrain_ml", "portfolio-ai", "Retrain ML", "cancel_in_progress", {"type": "cron", "value": "0 5 * * *", "timezone": "UTC"}),
    ("portfolio-ai/jenny_weekly_price_check", "portfolio-ai", "Weekly price check", "cancel_in_progress", {"type": "cron", "value": "30 13 * * 6", "timezone": "UTC"}),
    ("jobinator-4000/nightly_screen", "jobinator-4000", "Nightly screen", "group_round_robin", {}),
    ("jobinator-4000/nightly_enrich", "jobinator-4000", "Nightly enrich", "cancel_in_progress", {}),
    ("jobinator-4000/deferred_ab_sweep", "jobinator-4000", "Deferred A/B sweep", "cancel_in_progress", {}),
)


class AutomationValidationError(ValueError):
    pass


class RevisionConflict(ValueError):
    pass


class PolicyConfig(BaseModel):
    """Shared project limits. Absent values impose no new limit."""

    model_config = ConfigDict(extra="allow")

    concurrency_limit: int | None = Field(default=None, ge=1)
    daily_limit: int | None = Field(default=None, ge=1)
    cooldown_seconds: int | None = Field(default=None, ge=0)
    allowed_hours: list[int] | None = None
    filters: dict = Field(default_factory=dict)
    screening_cap: int | None = Field(default=None, ge=0)
    classification_cap: int | None = Field(default=None, ge=0)


def policy_schema_for(project_id: str) -> dict:
    schema = PolicyConfig.model_json_schema()
    schema["properties"] = {
        key: value for key, value in schema.get("properties", {}).items()
        if project_id == "jobinator-4000" or key not in {"screening_cap", "classification_cap"}
    }
    return schema


def external_config_schema(workflow_key: str) -> dict:
    if workflow_key == "summitflow/browser_workflow":
        return {
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "object",
                    "properties": {"schema_version": {"const": 1}, "steps": {"type": "array", "minItems": 1}},
                    "required": ["schema_version", "steps"],
                },
                "parameters": {"type": "object"},
                "target": {"enum": ["local-ai"]},
            },
            "required": ["workflow"],
            "additionalProperties": False,
        }
    if workflow_key.startswith("jobinator-4000/"):
        properties: dict = {"limit": {"type": ["integer", "null"], "minimum": 1}}
        if workflow_key == "jobinator-4000/nightly_screen":
            properties["notify"] = {"type": "boolean"}
        if workflow_key == "jobinator-4000/deferred_ab_sweep":
            properties["limit"] = {"type": "integer", "minimum": 1}
        return {"type": "object", "properties": properties, "additionalProperties": False}
    return {"type": "object", "additionalProperties": False}


def policy_sync_pending(policy: AutomationProjectPolicy) -> bool:
    return (
        policy.project_id == "jobinator-4000"
        and {"screening_cap", "classification_cap"}.issubset(policy.config or {})
        and policy.sync_revision < policy.revision
    )


def effective_gate_reasons(
    *,
    profile_enabled: bool,
    policy_enabled: bool,
    owner_gate_reasons: list[str],
    manual: bool,
    manual_when_disabled: bool,
) -> list[str]:
    reasons: list[str] = []
    if not policy_enabled:
        reasons.append("project_disabled")
    if not profile_enabled and not (manual and manual_when_disabled):
        reasons.append("profile_disabled")
    reasons.extend(owner_gate_reasons)
    return reasons


async def live_owner_gate_reasons(db: AsyncSession, profile: AutomationProfile) -> list[str]:
    """Return the owner gate reasons recorded on a profile, minus retired persona gates."""
    del db
    return [reason for reason in (profile.owner_gate_reasons or []) if reason not in {
        "project_permission_off", "persona_paused", "persona_not_onboarded",
        "heartbeat_interval_disabled", "persona_missing",
    }]


def occurrence_key(profile_id: str, scheduled_for: datetime) -> str:
    return f"scheduled:{profile_id}:{scheduled_for.astimezone(UTC).isoformat()}"


def next_due(
    schedule_type: str, schedule_value: str, schedule_timezone: str, after: datetime
) -> datetime | None:
    if schedule_type == "at":
        target = datetime.fromisoformat(schedule_value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=ZoneInfo(schedule_timezone))
        target = target.astimezone(UTC)
        return target if target > after else None
    if schedule_type == "every":
        return after + timedelta(milliseconds=int(schedule_value))
    zone = ZoneInfo(schedule_timezone)
    return croniter(schedule_value, after.astimezone(zone)).get_next(datetime).astimezone(UTC)


def ensure_future_one_time(data: dict, now: datetime) -> None:
    """Prevent new one-time profiles that can never become due."""
    if data["schedule_type"] == "at" and next_due(
        data["schedule_type"], data["schedule_value"], data["schedule_timezone"], now
    ) is None:
        raise AutomationValidationError("One-time schedule must be in the future")


def validate_profile_payload(payload: dict, definition: AutomationDefinition | None = None) -> dict:
    """Normalize a profile command before any mutation."""
    data = dict(payload)
    schedule_type = data.get("schedule_type")
    schedule_value = data.get("schedule_value")
    timezone = data.get("schedule_timezone") or "UTC"
    if schedule_type not in {"at", "every", "cron"}:
        raise AutomationValidationError("schedule_type must be at, every, or cron")
    if not isinstance(schedule_value, str) or not schedule_value.strip():
        raise AutomationValidationError("schedule_value is required")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise AutomationValidationError("schedule_timezone is invalid") from exc
    try:
        if schedule_type == "cron" and not croniter.is_valid(schedule_value):
            raise ValueError("invalid cron")
        if schedule_type == "every" and int(schedule_value) <= 0:
            raise ValueError("nonpositive interval")
        if schedule_type == "at":
            datetime.fromisoformat(schedule_value)
    except (ValueError, TypeError) as exc:
        raise AutomationValidationError("schedule_value is invalid") from exc
    data["schedule_timezone"] = timezone
    data["config"] = data.get("config") or {}
    if not isinstance(data["config"], dict):
        raise AutomationValidationError("config must be an object")
    if definition is not None:
        if (
            data.get("project_id") != definition.owner_project_id
            and definition.owner_project_id != "summitflow"
        ):
            raise AutomationValidationError("project_id does not own workflow_key")
        try:
            validate_json(data["config"], definition.config_schema or {"type": "object"})
        except JsonSchemaError as exc:
            raise AutomationValidationError(f"config: {exc.message}") from exc
    return data


def validate_policy_config(config: dict) -> dict:
    try:
        value = PolicyConfig.model_validate(config)
    except Exception as exc:
        raise AutomationValidationError(f"config: {exc}") from exc
    if value.allowed_hours is not None and any(hour < 0 or hour > 23 for hour in value.allowed_hours):
        raise AutomationValidationError("config.allowed_hours must contain hours 0 through 23")
    return value.model_dump(exclude_none=True, exclude_unset=True)


async def get_definition(db: AsyncSession, workflow_key: str) -> AutomationDefinition:
    row = (await db.execute(
        select(AutomationDefinition).where(AutomationDefinition.workflow_key == workflow_key)
        .order_by(AutomationDefinition.version.desc()).limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise KeyError(workflow_key)
    return row


async def get_policy(db: AsyncSession, project_id: str) -> AutomationProjectPolicy:
    row = await db.get(AutomationProjectPolicy, project_id)
    if row is None:
        row = AutomationProjectPolicy(project_id=project_id, enabled=True, config={}, revision=1)
        db.add(row)
        await db.flush()
    return row


async def update_policy(
    db: AsyncSession, project_id: str, *, enabled: bool, config: dict,
    expected_revision: int, changed_by: str | None,
) -> AutomationProjectPolicy:
    row = (await db.execute(
        select(AutomationProjectPolicy).where(AutomationProjectPolicy.project_id == project_id)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        if expected_revision != 0:
            raise RevisionConflict("policy revision has changed")
        row = AutomationProjectPolicy(project_id=project_id, revision=0)
        db.add(row)
    elif row.revision != expected_revision:
        raise RevisionConflict("policy revision has changed")
    row.enabled = enabled
    normalized = validate_policy_config(config)
    if project_id == "jobinator-4000" and not {
        "screening_cap", "classification_cap"
    }.issubset(normalized):
        raise AutomationValidationError(
            "Jobinator policy requires screening_cap and classification_cap"
        )
    row.config = normalized
    row.revision += 1
    row.updated_by = changed_by
    await db.flush()
    return row


def profile_snapshot(profile: AutomationProfile) -> dict:
    return {key: getattr(profile, key) for key in (
        "project_id", "subject_id", "workflow_key", "definition_version", "label",
        "schedule_type", "schedule_value", "schedule_timezone", "config", "enabled",
        "clock_owner", "owner_gate_reasons", "source_ref", "max_runs",
        "imported_unreviewed_count",
    )}


async def _record_revision(db: AsyncSession, profile: AutomationProfile, changed_by: str | None) -> None:
    db.add(AutomationProfileRevision(
        id=str(uuid4()), profile_id=profile.id, revision=profile.revision,
        snapshot=profile_snapshot(profile), changed_by=changed_by,
    ))
    await db.flush()


async def create_profile(db: AsyncSession, payload: dict, *, changed_by: str | None) -> AutomationProfile:
    definition = await get_definition(db, payload["workflow_key"])
    data = validate_profile_payload(payload, definition)
    now = datetime.now(UTC)
    ensure_future_one_time(data, now)
    if definition.workflow_key.startswith("agent-hub."):
        existing = (await db.execute(select(AutomationProfile.id).where(
            AutomationProfile.workflow_key == definition.workflow_key
        ).limit(1))).scalar_one_or_none()
        if existing is not None:
            raise AutomationValidationError("Static Agent Hub schedule already has a profile")
    profile = AutomationProfile(
        id=str(uuid4()), project_id=data["project_id"], subject_id=data.get("subject_id"),
        workflow_key=definition.workflow_key, definition_version=definition.version,
        label=data.get("label") or definition.label, schedule_type=data["schedule_type"],
        schedule_value=data["schedule_value"], schedule_timezone=data["schedule_timezone"],
        config=data["config"], enabled=data.get("enabled", False),
        clock_owner="central", owner_gate_reasons=[], revision=1,
        next_run_at=next_due(data["schedule_type"], data["schedule_value"], data["schedule_timezone"], now),
    )
    db.add(profile)
    await db.flush()
    await _record_revision(db, profile, changed_by)
    return profile


async def update_profile(
    db: AsyncSession, profile_id: str, payload: dict, *, changed_by: str | None
) -> AutomationProfile:
    profile = (await db.execute(
        select(AutomationProfile).where(AutomationProfile.id == profile_id).with_for_update()
    )).scalar_one_or_none()
    if profile is None:
        raise KeyError(profile_id)
    expected = payload.get("expected_revision")
    if expected != profile.revision:
        raise RevisionConflict("profile revision has changed")
    definition = await get_definition(db, profile.workflow_key)
    full = {**profile_snapshot(profile), **payload}
    data = validate_profile_payload(full, definition)
    for key in ("subject_id", "label", "schedule_type", "schedule_value", "schedule_timezone", "config", "enabled"):
        if key in payload:
            setattr(profile, key, (data[key] or definition.label) if key == "label" else data[key])
    if {"schedule_type", "schedule_value", "schedule_timezone"} & payload.keys():
        profile.next_run_at = next_due(
            profile.schedule_type, profile.schedule_value, profile.schedule_timezone, datetime.now(UTC)
        )
    if profile.clock_owner == "legacy" and profile.source_ref and profile.source_ref.startswith("static:"):
        control = await db.get(WorkflowScheduleControl, profile.source_ref.split(":", 1)[1])
        if control is None:
            control = WorkflowScheduleControl(schedule_id=profile.source_ref.split(":", 1)[1])
            db.add(control)
        control.enabled = profile.enabled
        control.updated_by = changed_by
    profile.revision += 1
    await _record_revision(db, profile, changed_by)
    return profile


async def _policy_gate_reasons(
    db: AsyncSession, policy: AutomationProjectPolicy, now: datetime
) -> list[str]:
    config = PolicyConfig.model_validate(policy.config or {})
    reasons: list[str] = []
    if config.allowed_hours is not None and now.hour not in config.allowed_hours:
        reasons.append("outside_allowed_hours")
    concurrency_limit = config.concurrency_limit
    if concurrency_limit is not None:
        query = select(func.count()).select_from(AutomationRun).where(
            AutomationRun.project_id == policy.project_id,
            AutomationRun.status.in_(["admitted", "dispatching", "dispatched", "accepted", "running"]),
        )
        active = (await db.scalar(query)) or 0
        if active >= concurrency_limit:
            reasons.append("project_concurrency_limit")
    daily_limit = config.daily_limit
    if daily_limit is not None:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = select(func.count()).select_from(AutomationRun).where(
            AutomationRun.project_id == policy.project_id,
            AutomationRun.created_at >= start,
            AutomationRun.status != "rejected",
        )
        today = (await db.scalar(query)) or 0
        if today >= daily_limit:
            reasons.append("project_daily_limit")
    cooldown_seconds = config.cooldown_seconds
    if cooldown_seconds:
        query = select(AutomationRun.created_at).where(
            AutomationRun.project_id == policy.project_id,
            AutomationRun.status != "rejected",
        )
        last = (await db.execute(query.order_by(AutomationRun.created_at.desc()).limit(1))).scalar_one_or_none()
        if last is not None and last > now - timedelta(seconds=cooldown_seconds):
            reasons.append("project_cooldown")
    return reasons


async def admit_run(
    db: AsyncSession, profile_id: str, *, trigger: str,
    scheduled_for: datetime | None = None, idempotency_key: str | None = None,
    requested_by: str | None = None,
) -> AutomationRun:
    """Serialize admission on the shared policy row; one occurrence yields one run."""
    profile = (await db.execute(
        select(AutomationProfile).where(AutomationProfile.id == profile_id).with_for_update()
    )).scalar_one_or_none()
    if profile is None:
        raise KeyError(profile_id)
    key = occurrence_key(profile_id, scheduled_for) if trigger == "scheduled" and scheduled_for else f"manual:{profile_id}:{idempotency_key or uuid4()}"
    existing = (await db.execute(select(AutomationRun).where(AutomationRun.occurrence_key == key))).scalar_one_or_none()
    if existing is not None:
        return existing
    definition = await db.get(AutomationDefinition, (profile.workflow_key, profile.definition_version))
    if definition is None:
        raise KeyError(profile.workflow_key)
    policy = (await db.execute(select(AutomationProjectPolicy).where(
        AutomationProjectPolicy.project_id == profile.project_id
    ).with_for_update())).scalar_one_or_none()
    if policy is None:
        policy = await get_policy(db, profile.project_id)
    now = datetime.now(UTC)
    owner_reasons = await live_owner_gate_reasons(db, profile)
    profile.owner_gate_reasons = owner_reasons
    reasons = effective_gate_reasons(
        profile_enabled=profile.enabled, policy_enabled=policy.enabled,
        owner_gate_reasons=owner_reasons,
        manual=trigger == "manual", manual_when_disabled=definition.manual_when_disabled,
    )
    reasons.extend(await _policy_gate_reasons(db, policy, now))
    if profile.workflow_key == "summitflow/browser_workflow":
        # A human handoff is still active. Serialize against the profile lock
        # held above so a new occurrence never supersedes its owned session.
        active = await db.scalar(select(func.count()).select_from(AutomationRun).where(
            AutomationRun.profile_id == profile.id,
            AutomationRun.status.in_(["admitted", "dispatching", "dispatched", "accepted", "running"]),
        ))
        if active:
            reasons.append("profile_overlap_cancel_newest")
    if policy_sync_pending(policy):
        reasons.append("owner_policy_sync_pending")
    if trigger == "scheduled" and profile.clock_owner != "central":
        reasons.append("legacy_clock_owner")
    run = AutomationRun(
        id=str(uuid4()), profile_id=profile.id, project_id=profile.project_id,
        workflow_key=profile.workflow_key, definition_version=profile.definition_version,
        profile_revision=profile.revision, trigger=trigger, occurrence_key=key,
        scheduled_for=scheduled_for, status="rejected" if reasons else "admitted",
        gate_reasons=reasons, config_snapshot=dict(profile.config or {}),
        policy_snapshot=dict(policy.config or {}),
        requested_by=requested_by, owner_receipt={},
    )
    db.add(run)
    if trigger == "scheduled" and scheduled_for is not None:
        profile.next_run_at = next_due(
            profile.schedule_type, profile.schedule_value, profile.schedule_timezone, scheduled_for
        )
    if not reasons and (trigger == "scheduled" or definition.manual_advances_cursor):
        profile.last_run_at = now
        profile.run_count += 1
        if profile.max_runs is not None and profile.run_count >= profile.max_runs:
            profile.enabled = False
            profile.next_run_at = None
        elif trigger == "manual" and definition.manual_advances_cursor:
            profile.next_run_at = next_due(
                profile.schedule_type, profile.schedule_value, profile.schedule_timezone, now
            )
    await db.flush()
    return run


async def import_agent_hub_legacy(db: AsyncSession) -> None:
    """Idempotently mirror current AH settings; imported clocks remain legacy-owned."""
    controls = {row.schedule_id: row for row in (
        await db.execute(select(WorkflowScheduleControl))
    ).scalars().all()}
    existing = {row.source_ref: row for row in (
        await db.execute(select(AutomationProfile).where(AutomationProfile.source_ref.is_not(None)))
    ).scalars().all()}
    now = datetime.now(UTC)
    for key, project_id, label, overlap, default_schedule in EXTERNAL_WORKFLOWS:
        if await db.get(AutomationDefinition, (key, 1)) is None:
            db.add(AutomationDefinition(
                workflow_key=key, version=1, owner_project_id=project_id,
                label=label, description=f"{label} owned by {project_id}.",
                dispatch_kind="callback", dispatch_target=f"/automations/dispatch/{key.split('/', 1)[1]}",
                config_schema=external_config_schema(key),
                policy_schema=policy_schema_for(project_id),
                default_schedule=default_schedule, default_enabled=key != "summitflow/browser_workflow",
                manual_when_disabled=key in {"summitflow/browser_workflow", "portfolio-ai/jenny_weekly_price_check"},
                manual_advances_cursor=False,
                overlap_strategy=overlap,
            ))
    for schedule in SCHEDULE_DEFINITIONS:
        key = f"agent-hub.{schedule.schedule_id}"
        definition = await db.get(AutomationDefinition, (key, 1))
        if definition is None:
            definition = AutomationDefinition(
                workflow_key=key, version=1, owner_project_id="agent-hub",
                label=schedule.label, description=schedule.description,
                dispatch_kind="hatchet", dispatch_target=schedule.schedule_id,
                config_schema={"type": "object", "additionalProperties": False},
                policy_schema=policy_schema_for("agent-hub"),
                default_schedule={"type": "cron", "value": schedule.cron, "timezone": "UTC"},
                default_enabled=schedule.default_enabled,
                manual_when_disabled=True, manual_advances_cursor=False,
                overlap_strategy="cancel_in_progress",
            )
            db.add(definition)
        source = f"static:{schedule.schedule_id}"
        control = controls.get(schedule.schedule_id)
        enabled = control.enabled if control else schedule.default_enabled
        profile = existing.get(source)
        if profile is None:
            profile = AutomationProfile(
                id=str(uuid4()), project_id="agent-hub", workflow_key=key,
                definition_version=1, label=schedule.label, schedule_type="cron",
                schedule_value=schedule.cron, schedule_timezone="UTC", config={},
                enabled=enabled, clock_owner="legacy", owner_gate_reasons=[], source_ref=source,
                next_run_at=next_due("cron", schedule.cron, "UTC", now),
                revision=1,
            )
            db.add(profile)
            await db.flush()
            await _record_revision(db, profile, "legacy-import")
        elif profile.clock_owner == "legacy":
            profile.enabled = enabled

    for project_id in {"agent-hub", *(item[1] for item in EXTERNAL_WORKFLOWS)}:
        if await db.get(AutomationProjectPolicy, project_id) is None:
            db.add(AutomationProjectPolicy(project_id=project_id, enabled=True, config={}, revision=1))
    await db.flush()
