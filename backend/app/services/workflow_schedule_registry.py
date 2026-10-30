"""Registry and persistence helpers for static Hatchet workflow schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import WorkflowScheduleControl

ScheduleCategory = Literal["maintenance", "memory", "observability", "catalog"]


@dataclass(frozen=True)
class WorkflowScheduleDefinition:
    """UI-facing metadata for a static cron workflow."""

    schedule_id: str
    label: str
    description: str
    cron: str
    category: ScheduleCategory
    default_enabled: bool = True
    notes: str | None = None


class WorkflowScheduleState(TypedDict):
    schedule_id: str
    label: str
    description: str
    cron: str
    category: ScheduleCategory
    default_enabled: bool
    enabled: bool
    notes: str | None
    updated_by: str | None


SCHEDULE_DEFINITIONS: tuple[WorkflowScheduleDefinition, ...] = (
    WorkflowScheduleDefinition(
        schedule_id="session_cleanup",
        label="Session cleanup",
        description="Marks dead candidate sessions completed when the cleanup heuristics say they are done.",
        cron="*/15 * * * *",
        category="maintenance",
    ),
    WorkflowScheduleDefinition(
        schedule_id="session_reaper",
        label="Session reaper",
        description="Hard-closes long-stale active sessions that never finalized cleanly.",
        cron="*/30 * * * *",
        category="maintenance",
    ),
    WorkflowScheduleDefinition(
        schedule_id="tier_optimizer",
        label="Tier optimizer",
        description="Rebalances memory tiers and lifecycle scores.",
        cron="0 2 * * *",
        category="memory",
    ),
    WorkflowScheduleDefinition(
        schedule_id="memory_cleanup",
        label="Memory cleanup",
        description="Retires stale memories and consolidates redundant ones.",
        cron="0 3 * * 0",
        category="memory",
    ),
    WorkflowScheduleDefinition(
        schedule_id="memory_governance",
        label="Memory governance",
        description="Collects memory-governance health and policy drift snapshots.",
        cron="15 3 * * *",
        category="memory",
    ),
    WorkflowScheduleDefinition(
        schedule_id="data_retention",
        label="Data retention",
        description="Deletes expired telemetry and request logs; archives old finished sessions' events.",
        cron="0 4 * * *",
        category="maintenance",
    ),
    WorkflowScheduleDefinition(
        schedule_id="local_history",
        label="Local agent history",
        description=(
            "Imports Claude Code turns and subagents the Stop hook missed, then deletes local Claude Code, "
            "Codex and Pi transcripts idle past the retention days once Agent Hub holds all of them."
        ),
        cron="30 4 * * *",
        category="maintenance",
    ),
    WorkflowScheduleDefinition(
        schedule_id="model_enrichment_sync",
        label="Model enrichment sync",
        description="Refreshes model benchmark, pricing, catalog, and routable availability data.",
        cron="0 6 * * *",
        category="catalog",
    ),
)

_SCHEDULE_INDEX = {definition.schedule_id: definition for definition in SCHEDULE_DEFINITIONS}


def list_workflow_schedule_definitions() -> tuple[WorkflowScheduleDefinition, ...]:
    return SCHEDULE_DEFINITIONS


def get_workflow_schedule_definition(schedule_id: str) -> WorkflowScheduleDefinition:
    definition = _SCHEDULE_INDEX.get(schedule_id)
    if definition is None:
        raise KeyError(schedule_id)
    return definition


def _to_state(
    definition: WorkflowScheduleDefinition,
    control: WorkflowScheduleControl | None,
) -> WorkflowScheduleState:
    return {
        "schedule_id": definition.schedule_id,
        "label": definition.label,
        "description": definition.description,
        "cron": definition.cron,
        "category": definition.category,
        "default_enabled": definition.default_enabled,
        "enabled": bool(control.enabled) if control is not None else definition.default_enabled,
        "notes": definition.notes,
        "updated_by": control.updated_by if control is not None else None,
    }


async def _load_controls(
    db: AsyncSession,
    schedule_ids: list[str],
) -> dict[str, WorkflowScheduleControl]:
    result = await db.execute(
        select(WorkflowScheduleControl).where(WorkflowScheduleControl.schedule_id.in_(schedule_ids))
    )
    controls = result.scalars().all()
    return {control.schedule_id: control for control in controls}


async def list_workflow_schedule_states(
    db: AsyncSession | None = None,
) -> list[WorkflowScheduleState]:
    """Return schedule states with defaults applied for missing rows."""
    if db is None:
        async with async_session() as session:
            return await list_workflow_schedule_states(session)

    definitions = list(SCHEDULE_DEFINITIONS)
    controls = await _load_controls(db, [definition.schedule_id for definition in definitions])
    return [_to_state(definition, controls.get(definition.schedule_id)) for definition in definitions]


async def describe_workflow_schedule(
    schedule_id: str,
    db: AsyncSession | None = None,
) -> WorkflowScheduleState:
    """Return one schedule state with defaults applied."""
    if db is None:
        async with async_session() as session:
            return await describe_workflow_schedule(schedule_id, session)

    definition = get_workflow_schedule_definition(schedule_id)
    control = await db.get(WorkflowScheduleControl, schedule_id)
    return _to_state(definition, control)


async def is_workflow_schedule_enabled(
    schedule_id: str,
    db: AsyncSession | None = None,
    *,
    automation_run_id: str | None = None,
) -> bool:
    """Return whether a static cron workflow is enabled."""
    if db is None:
        async with async_session() as session:
            return await is_workflow_schedule_enabled(
                schedule_id, session, automation_run_id=automation_run_id
            )
    # The profile row is the durable one-clock fence. Old Hatchet cron ticks
    # carry no run ID, while central dispatches carry an admitted run ID.
    from app.models import AutomationProfile, AutomationRun
    from app.models.automation import RUN_ACTIVE_STATUSES

    profile = (await db.execute(select(AutomationProfile).where(
        AutomationProfile.source_ref == f"static:{schedule_id}"
    ))).scalar_one_or_none()
    if automation_run_id and profile is not None:
        run = await db.get(AutomationRun, automation_run_id)
        if run and run.profile_id == profile.id and run.status in RUN_ACTIVE_STATUSES and (
            profile.clock_owner == "central" or run.trigger == "manual"
        ):
            return True
    if profile is not None and profile.clock_owner == "central":
        return False
    return bool((await describe_workflow_schedule(schedule_id, db))["enabled"])


async def set_workflow_schedule_enabled(
    schedule_id: str,
    *,
    enabled: bool,
    updated_by: str | None = None,
    db: AsyncSession | None = None,
) -> WorkflowScheduleState:
    """Persist enable/disable state for one schedule."""
    if db is None:
        async with async_session() as session:
            state = await set_workflow_schedule_enabled(
                schedule_id,
                enabled=enabled,
                updated_by=updated_by,
                db=session,
            )
            await session.commit()
            return state

    definition = get_workflow_schedule_definition(schedule_id)
    control = await db.get(WorkflowScheduleControl, schedule_id)
    if control is None:
        control = WorkflowScheduleControl(schedule_id=schedule_id)
        db.add(control)

    control.enabled = enabled
    control.updated_by = updated_by
    from app.models import AutomationProfile

    profile = (await db.execute(select(AutomationProfile).where(
        AutomationProfile.source_ref == f"static:{schedule_id}"
    ))).scalar_one_or_none()
    if profile is not None and profile.clock_owner == "legacy":
        profile.enabled = enabled
    await db.flush()
    await db.refresh(control)
    return _to_state(definition, control)
