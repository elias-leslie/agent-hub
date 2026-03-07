"""Persona scheduler — execute due scheduled jobs every minute.

Polls persona_scheduled_jobs for enabled jobs with next_run_at <= now(),
executes each one (agent_turn or push), updates run tracking, and
computes the next run time.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Context
from pydantic import BaseModel

from app.hatchet_app import hatchet

logger = logging.getLogger(__name__)

SCHEDULER_PROJECT = "agent-hub"
SCHEDULER_MEMORY_GROUP = "agent-hub:scheduler"


class SchedulerResult(BaseModel):
    status: str
    jobs_executed: int = 0
    errors: list[str] | None = None


def compute_next_run(
    schedule_type: str,
    schedule_value: str,
    timezone: str = "UTC",
    last_run_at: datetime | None = None,
) -> datetime | None:
    """Compute the next run time for a scheduled job.

    Args:
        schedule_type: "at", "every", or "cron"
        schedule_value: ISO datetime, interval in ms, or cron expression
        timezone: IANA timezone string
        last_run_at: When the job last ran (None if never)

    Returns:
        Next run datetime (UTC), or None for completed one-shots.
    """
    now = datetime.now(UTC)

    if schedule_type == "at":
        # One-shot — parse ISO datetime
        target = datetime.fromisoformat(schedule_value)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        return target if target > now else None

    if schedule_type == "every":
        # Interval in milliseconds
        interval_ms = int(schedule_value)
        interval = timedelta(milliseconds=interval_ms)
        base = last_run_at if last_run_at else now
        next_time = base + interval
        # If next_time is in the past (e.g., after long downtime), snap to now + interval
        if next_time <= now:
            next_time = now + interval
        return next_time

    if schedule_type == "cron":
        from croniter import croniter

        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(timezone)
        except Exception:
            import zoneinfo
            tz = zoneinfo.ZoneInfo("UTC")

        base = (last_run_at or now).astimezone(tz)
        cron = croniter(schedule_value, base)
        next_time = cron.get_next(datetime)
        return next_time.astimezone(UTC)

    return None


async def _execute_agent_turn(job: Any) -> str:
    """Execute a scheduled job as an agent turn via complete_internal."""
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services._persona_crud import get_persona_limit
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates
    from app.services.agent_service import get_agent_service
    from app.services.project_permission_service import get_project_permission

    # Check project permission — skip if tier is "off"
    async with async_session() as perm_db:
        perm = await get_project_permission(perm_db, SCHEDULER_PROJECT)
        if perm and perm.permission_tier == "off":
            return "Skipped: project permission tier is off"

    async with async_session() as db:
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, "persona")
        if not agent:
            return "Error: persona agent not found"

        provider = get_provider_for_model(agent.primary_model_id)
        mandate = await inject_agent_mandates(
            agent, db, prompt_mode="full", project_id=SCHEDULER_PROJECT, task_type="scheduled_job"
        )

        messages: list[dict[str, Any]] = []
        if mandate.system_content:
            messages.append({"role": "system", "content": mandate.system_content})
        messages.append({"role": "user", "content": job.payload_message})

        # Get configurable max_turns from persona
        from app.services.persona_service import get_persona

        persona = await get_persona(db)
        max_turns = get_persona_limit(persona, "max_turns")

        result = await complete_internal(
            messages=messages,
            model=agent.primary_model_id,
            provider=provider,
            temperature=agent.temperature,
            project_id=SCHEDULER_PROJECT,
            db=db,
            agent_slug="persona",
            use_memory=True,
            memory_group_id=SCHEDULER_MEMORY_GROUP,
            enable_caching=False,
            skip_cache=True,
            max_turns=max_turns,
            execute_tools=True,
            enable_programmatic_tools=True,
            defer_tool_loading=True,
            task_type="scheduled_job",
            thinking_level=agent.thinking_level,
        )
        return result.content[:500] if result.content else "(no output)"


async def _execute_push(job: Any) -> str:
    """Execute a scheduled job as a push notification."""
    from app.db import async_session
    from app.services.push_service import send_push

    payload: dict[str, str] = {
        "title": job.payload_title or job.name,
        "body": job.payload_message,
    }

    async with async_session() as db:
        sent = await send_push(db, payload=payload)

    return f"Push sent to {sent} device(s)"


@hatchet.task(
    name="persona-scheduler",
    input_validator=BaseModel,
    on_crons=["* * * * *"],
    execution_timeout="7200s",
    concurrency=ConcurrencyExpression(
        expression="'persona_scheduler'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.CANCEL_IN_PROGRESS,
    ),
)
async def persona_scheduler_task(input: BaseModel, ctx: Context) -> dict[str, Any]:
    """Poll and execute due scheduled jobs."""
    from sqlalchemy import select

    from app.db import async_session
    from app.models.persona_scheduled_job import PersonaScheduledJob

    errors: list[str] = []
    executed = 0

    async with async_session() as db:
        now = datetime.now(UTC)
        result = await db.execute(
            select(PersonaScheduledJob).where(
                PersonaScheduledJob.enabled.is_(True),
                PersonaScheduledJob.next_run_at <= now,
            )
        )
        jobs = result.scalars().all()

        if not jobs:
            return SchedulerResult(status="idle").model_dump()

        for job in jobs:
            try:
                if job.payload_type == "push":
                    output = await _execute_push(job)
                else:
                    output = await _execute_agent_turn(job)

                # Delivery notification
                if job.delivery == "push" and job.payload_type == "agent_turn":
                    try:
                        from app.services.push_service import send_push

                        async with async_session() as push_db:
                            await send_push(push_db, payload={
                                "title": f"Scheduled: {job.name}",
                                "body": output[:200],
                                "tag": f"scheduled:{job.id}",
                            })
                    except Exception:
                        logger.debug("Delivery push failed for job %s", job.id)

                job.last_run_at = now
                job.run_count += 1

                # Compute next run
                next_run = compute_next_run(
                    job.schedule_type, job.schedule_value,
                    job.schedule_timezone, job.last_run_at,
                )
                job.next_run_at = next_run

                # Auto-disable completed one-shots or max-run jobs
                if job.max_runs is not None and job.run_count >= job.max_runs:
                    job.enabled = False

                executed += 1
                logger.info("Scheduled job %s (%s) executed", job.name, job.id)

            except Exception as e:
                logger.exception("Scheduled job %s failed", job.id)
                errors.append(f"{job.name}: {e}")

        await db.commit()

    ctx.log(f"Scheduler: {executed} jobs executed, {len(errors)} errors")
    return SchedulerResult(
        status="executed" if executed else "idle",
        jobs_executed=executed,
        errors=errors or None,
    ).model_dump()
