"""Scheduling tool implementations for DirectToolExecutor.

Handles job scheduling, listing, and cancellation.
"""

from __future__ import annotations

import logging

from app.models.persona_scheduled_job import PersonaScheduledJob

logger = logging.getLogger(__name__)

_VALID_PAYLOAD_TYPES = frozenset({"agent_turn", "push", "self_honing", "memory_review"})


async def schedule_job(
    name: str,
    schedule_type: str,
    schedule_value: str,
    payload_message: str,
    payload_type: str = "agent_turn",
    delivery: str = "none",
    timezone: str = "UTC",
) -> str:
    """Create a scheduled job for the persona."""
    if schedule_type not in ("at", "every", "cron"):
        return f"Error: Invalid schedule_type '{schedule_type}'. Must be at/every/cron."
    if payload_type not in _VALID_PAYLOAD_TYPES:
        return (
            f"Error: Invalid payload_type '{payload_type}'. "
            "Must be agent_turn/push/self_honing/memory_review."
        )

    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona
        from app.workflows.persona_scheduler import compute_next_run

        async with async_session() as db:
            persona = await get_or_create_persona(db)

            next_run = compute_next_run(schedule_type, schedule_value, timezone)
            if next_run is None and schedule_type == "at":
                return "Error: Scheduled time is in the past."

            max_runs = 1 if schedule_type == "at" else None

            job = PersonaScheduledJob(
                persona_id=persona.id,
                name=name,
                schedule_type=schedule_type,
                schedule_value=schedule_value,
                schedule_timezone=timezone,
                payload_type=payload_type,
                payload_message=payload_message,
                delivery=delivery,
                next_run_at=next_run,
                max_runs=max_runs,
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

        next_str = next_run.isoformat() if next_run else "N/A"
        return f"Job '{name}' scheduled (id={job.id}). Next run: {next_str}"
    except Exception as e:
        logger.exception("schedule_job failed")
        return f"Error scheduling job: {e}"


async def list_scheduled_jobs(include_disabled: bool = False) -> str:
    """List scheduled jobs for the persona."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.persona_scheduled_job import PersonaScheduledJob
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            query = select(PersonaScheduledJob).where(
                PersonaScheduledJob.persona_id == persona.id
            )
            if not include_disabled:
                query = query.where(PersonaScheduledJob.enabled.is_(True))
            query = query.order_by(PersonaScheduledJob.next_run_at)

            result = await db.execute(query)
            jobs = result.scalars().all()

        if not jobs:
            return "(No scheduled jobs)"

        lines = []
        for job in jobs:
            status = "enabled" if job.enabled else "disabled"
            next_str = job.next_run_at.isoformat() if job.next_run_at else "N/A"
            runs = f"{job.run_count}"
            if job.max_runs:
                runs += f"/{job.max_runs}"
            lines.append(
                f"- **{job.name}** (id={job.id})\n"
                f"  {job.schedule_type}={job.schedule_value} | type={job.payload_type} | "
                f"next={next_str} | runs={runs} | {status}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.exception("list_scheduled_jobs failed")
        return f"Error listing jobs: {e}"


async def cancel_scheduled_job(job_id: str, hard_delete: bool = False) -> str:
    """Disable or delete a scheduled job."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.persona_scheduled_job import PersonaScheduledJob

        async with async_session() as db:
            result = await db.execute(
                select(PersonaScheduledJob).where(PersonaScheduledJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return f"Error: Job '{job_id}' not found."

            name = job.name
            if hard_delete:
                await db.delete(job)
                await db.commit()
                return f"Job '{name}' (id={job_id}) permanently deleted."

            job.enabled = False
            await db.commit()
            return f"Job '{name}' (id={job_id}) disabled."
    except Exception as e:
        logger.exception("cancel_scheduled_job failed")
        return f"Error cancelling job: {e}"
