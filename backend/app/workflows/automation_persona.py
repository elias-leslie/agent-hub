"""Execute one canonical persona profile through the existing job executor."""

from datetime import UTC, datetime
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel
from sqlalchemy import select

from app.db import async_session
from app.hatchet_app import hatchet
from app.models import AutomationProfile, AutomationRun, PersonaScheduledJob
from app.services.automations import next_due
from app.workflows.persona_scheduler import (
    _maybe_send_delivery_push,
    _maybe_send_delivery_telegram,
    execute_job,
)


class AutomationPersonaInput(BaseModel):
    automation_run_id: str


@hatchet.task(name="automation-persona-job", input_validator=AutomationPersonaInput)
async def automation_persona_job_task(input: AutomationPersonaInput, ctx: Context) -> dict[str, Any]:
    async with async_session() as db:
        run = (await db.execute(select(AutomationRun).where(
            AutomationRun.id == input.automation_run_id
        ).with_for_update())).scalar_one_or_none()
        if run is None:
            return {"status": "missing"}
        if run.status in {"running", "succeeded", "failed", "skipped", "cancelled"}:
            return {"status": "duplicate", "run_id": run.id}
        profile = await db.get(AutomationProfile, run.profile_id)
        if profile is None or not profile.source_ref or not profile.source_ref.startswith("persona:"):
            run.status = "failed"
            run.error = "Persona source job missing"
            run.completed_at = datetime.now(UTC)
            await db.commit()
            return {"status": "failed", "run_id": run.id}
        job = await db.get(PersonaScheduledJob, profile.source_ref.split(":", 1)[1])
        if job is None:
            run.status = "failed"
            run.error = "Persona source job missing"
            run.completed_at = datetime.now(UTC)
            await db.commit()
            return {"status": "failed", "run_id": run.id}
        run.status = "running"
        run.owner_run_id = run.id
        run.accepted_at = run.accepted_at or datetime.now(UTC)
        await db.commit()

    try:
        result = await execute_job(job)
        await _maybe_send_delivery_push(job, result.output)
        await _maybe_send_delivery_telegram(job, result.output)
        status = "skipped" if result.output.startswith("Skipped:") else "succeeded"
        error = None
    except Exception as exc:
        status = "failed"
        error = str(exc)
        result = None

    now = datetime.now(UTC)
    async with async_session() as db:
        run = await db.get(AutomationRun, input.automation_run_id)
        profile = await db.get(AutomationProfile, run.profile_id) if run else None
        job = await db.get(PersonaScheduledJob, profile.source_ref.split(":", 1)[1]) if profile and profile.source_ref else None
        if run and run.status == "running":
            run.status = status
            run.error = error
            run.owner_receipt = {"session_id": result.session_id, "output": result.output} if result else {}
            run.completed_at = now
            if profile and job and status in {"succeeded", "skipped"}:
                profile.last_run_at = now
                profile.run_count += 1
                profile.next_run_at = next_due(
                    profile.schedule_type, profile.schedule_value, profile.schedule_timezone, now
                ) if profile.enabled else None
                if profile.max_runs is not None and profile.run_count >= profile.max_runs:
                    profile.enabled = False
                    profile.next_run_at = None
                job.last_run_at = now
                job.run_count = profile.run_count
                job.max_runs = profile.max_runs
                job.enabled = profile.enabled if profile.clock_owner == "legacy" else False
                job.next_run_at = profile.next_run_at if profile.clock_owner == "legacy" else None
            await db.commit()
    ctx.log(f"Persona automation {input.automation_run_id}: {status}")
    return {"status": status, "run_id": input.automation_run_id}
