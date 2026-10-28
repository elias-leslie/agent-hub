"""Canonical automation admission, validation, and legacy-state import."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from jsonschema import Draft202012Validator, SchemaError
from jsonschema import ValidationError as JsonSchemaError
from jsonschema import validate as validate_json
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
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

# Owner-added policy keys: required in that project's shared policy and mirrored to the
# owner (POST /automations/policy/sync) whenever the policy revision changes.
OWNER_POLICY_KEYS = "x-owner-keys"
OVERLAP_STRATEGIES = frozenset({"cancel_in_progress", "cancel_newest", "group_round_robin"})
_WORKFLOW_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


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


def shared_policy_schema() -> dict:
    """The project policy keys every owner shares (limits Agent Hub enforces)."""
    return PolicyConfig.model_json_schema()


def owner_policy_keys(definitions: list[AutomationDefinition]) -> list[str]:
    """Policy keys the owner registered on any of its current definitions."""
    keys: set[str] = set()
    for definition in definitions:
        keys.update((definition.policy_schema or {}).get(OWNER_POLICY_KEYS) or [])
    return sorted(keys)


async def current_definitions(db: AsyncSession, project_id: str | None = None) -> list[AutomationDefinition]:
    """Latest version of each definition, optionally only one owner's."""
    query = select(AutomationDefinition)
    if project_id is not None:
        query = query.where(AutomationDefinition.owner_project_id == project_id)
    latest: dict[str, AutomationDefinition] = {}
    for row in (await db.execute(query)).scalars().all():
        if row.workflow_key not in latest or row.version > latest[row.workflow_key].version:
            latest[row.workflow_key] = row
    return list(latest.values())


async def project_owner_keys(db: AsyncSession, project_id: str) -> list[str]:
    return owner_policy_keys(await current_definitions(db, project_id))


def policy_sync_pending(policy: AutomationProjectPolicy, owner_keys: list[str]) -> bool:
    return (
        bool(owner_keys)
        and set(owner_keys).issubset(policy.config or {})
        and policy.sync_revision < policy.revision
    )


async def owner_sync_pending(db: AsyncSession, policy: AutomationProjectPolicy) -> bool:
    """Whether the owner has yet to acknowledge this policy revision."""
    if policy.sync_revision >= policy.revision:
        return False
    return policy_sync_pending(policy, await project_owner_keys(db, policy.project_id))


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
    definitions = await current_definitions(db, project_id)
    owner_keys = owner_policy_keys(definitions)
    if owner_keys and not set(owner_keys).issubset(normalized):
        raise AutomationValidationError(f"{project_id} policy requires {', '.join(owner_keys)}")
    for definition in definitions:
        try:
            validate_json(normalized, definition.policy_schema or {"type": "object"})
        except JsonSchemaError as exc:
            raise AutomationValidationError(f"config: {exc.message}") from exc
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
    if definition.overlap_strategy == "cancel_newest":
        # An earlier occurrence (e.g. a human handoff) is still active. Serialize
        # against the profile lock held above so a new one never supersedes it.
        active = await db.scalar(select(func.count()).select_from(AutomationRun).where(
            AutomationRun.profile_id == profile.id,
            AutomationRun.status.in_(["admitted", "dispatching", "dispatched", "accepted", "running"]),
        ))
        if active:
            reasons.append("profile_overlap_cancel_newest")
    if await owner_sync_pending(db, policy):
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
    for schedule in SCHEDULE_DEFINITIONS:
        key = f"agent-hub.{schedule.schedule_id}"
        definition = await db.get(AutomationDefinition, (key, 1))
        if definition is None:
            definition = AutomationDefinition(
                workflow_key=key, version=1, owner_project_id="agent-hub",
                label=schedule.label, description=schedule.description,
                dispatch_kind="hatchet", dispatch_target=schedule.schedule_id,
                config_schema={"type": "object", "additionalProperties": False},
                policy_schema=shared_policy_schema(),
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

    if await db.get(AutomationProjectPolicy, "agent-hub") is None:
        db.add(AutomationProjectPolicy(project_id="agent-hub", enabled=True, config={}, revision=1))
    await db.flush()
    await retire_removed_agent_hub_schedules(db)


_FINISHED_RUN_STATUSES = ("succeeded", "failed", "skipped", "cancelled", "rejected")
# Schedules deleted from SCHEDULE_DEFINITIONS whose catalog rows are pruned. Listed
# explicitly so a schedule that is only renamed or briefly missing keeps its history.
RETIRED_AGENT_HUB_SCHEDULES = ("agent-hub.feedback_cleanup",)


async def retire_removed_agent_hub_schedules(db: AsyncSession) -> list[str]:
    """Delete the catalog entries of Agent Hub schedules retired from the code.

    Their Hatchet task is gone, so the definition, its static profile (revisions
    cascade) and its finished run receipts can never be used again. A definition
    with a run still in flight is kept until that run finishes.
    """
    current = {f"agent-hub.{schedule.schedule_id}" for schedule in SCHEDULE_DEFINITIONS}
    retired_keys = [key for key in RETIRED_AGENT_HUB_SCHEDULES if key not in current]
    if not retired_keys:
        return []
    rows = (await db.execute(select(AutomationDefinition).where(
        AutomationDefinition.owner_project_id == "agent-hub",
        AutomationDefinition.dispatch_kind == "hatchet",
        AutomationDefinition.workflow_key.in_(retired_keys),
    ))).scalars().all()
    retired: list[str] = []
    for key in sorted({row.workflow_key for row in rows}):
        in_flight = await db.scalar(select(func.count()).select_from(AutomationRun).where(
            AutomationRun.workflow_key == key,
            AutomationRun.status.not_in(_FINISHED_RUN_STATUSES),
        ))
        if in_flight:
            logger.warning("Keeping retired automation %s until %d run(s) finish", key, in_flight)
            continue
        await db.execute(delete(AutomationRun).where(AutomationRun.workflow_key == key))
        await db.execute(delete(AutomationProfile).where(AutomationProfile.workflow_key == key))
        await db.execute(delete(AutomationDefinition).where(AutomationDefinition.workflow_key == key))
        retired.append(key)
    if retired:
        logger.info("Retired removed Agent Hub automations: %s", ", ".join(retired))
    return retired


class DefinitionRegistration(BaseModel):
    """What an owner project declares about one of its callback workflows."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    description: str = ""
    config_schema: dict = Field(default_factory=lambda: {"type": "object", "additionalProperties": False})
    # Extra policy keys this owner adds to its project's shared policy (JSON Schema
    # properties). They become required there and are mirrored to the owner.
    policy_properties: dict[str, dict] = Field(default_factory=dict)
    default_schedule: dict = Field(default_factory=dict)
    default_enabled: bool = True
    manual_when_disabled: bool = False
    manual_advances_cursor: bool = False
    overlap_strategy: str = "cancel_in_progress"


def _check_schema(name: str, schema: dict) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise AutomationValidationError(f"{name}: {exc.message}") from exc


async def register_definition(
    db: AsyncSession, owner_project_id: str, name: str, registration: DefinitionRegistration,
) -> AutomationDefinition:
    """Create or update an owner's callback definition in place.

    The dispatch route is always the owner's /automations/dispatch/{name}; an owner
    cannot point Agent Hub at another URL or register another project's workflow.
    """
    if not _WORKFLOW_NAME.match(name):
        raise AutomationValidationError("workflow name must be lowercase letters, digits, '_' or '-'")
    if owner_project_id == "agent-hub":
        raise AutomationValidationError("Agent Hub's own schedules are not registered")
    if registration.overlap_strategy not in OVERLAP_STRATEGIES:
        raise AutomationValidationError(
            f"overlap_strategy must be one of {', '.join(sorted(OVERLAP_STRATEGIES))}"
        )
    _check_schema("config_schema", registration.config_schema)
    shared = shared_policy_schema()
    clash = set(registration.policy_properties) & set(shared.get("properties", {}))
    if clash:
        raise AutomationValidationError(f"policy_properties may not redefine {', '.join(sorted(clash))}")
    owner_keys = sorted(registration.policy_properties)
    policy_schema = {
        **shared,
        "properties": {**shared.get("properties", {}), **registration.policy_properties},
        "required": owner_keys,
        OWNER_POLICY_KEYS: owner_keys,
    }
    _check_schema("policy_properties", policy_schema)
    if registration.default_schedule:
        schedule = registration.default_schedule
        validate_profile_payload({
            "schedule_type": schedule.get("type"), "schedule_value": schedule.get("value"),
            "schedule_timezone": schedule.get("timezone"),
        })
    values = {
        "owner_project_id": owner_project_id, "label": registration.label,
        "description": registration.description or f"{registration.label} owned by {owner_project_id}.",
        "dispatch_kind": "callback", "dispatch_target": f"/automations/dispatch/{name}",
        "config_schema": registration.config_schema, "policy_schema": policy_schema,
        "default_schedule": registration.default_schedule,
        "default_enabled": registration.default_enabled,
        "manual_when_disabled": registration.manual_when_disabled,
        "manual_advances_cursor": registration.manual_advances_cursor,
        "overlap_strategy": registration.overlap_strategy,
    }
    workflow_key = f"{owner_project_id}/{name}"
    try:
        row = await get_definition(db, workflow_key)
    except KeyError:
        row = AutomationDefinition(workflow_key=workflow_key, version=1, **values)
        db.add(row)
    else:
        if row.owner_project_id != owner_project_id:
            raise AutomationValidationError("workflow_key belongs to another project")
        for key, value in values.items():
            setattr(row, key, value)
    if await db.get(AutomationProjectPolicy, owner_project_id) is None:
        db.add(AutomationProjectPolicy(project_id=owner_project_id, enabled=True, config={}, revision=1))
    await db.flush()
    return row
