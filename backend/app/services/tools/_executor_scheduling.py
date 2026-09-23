"""Persona scheduling tools backed by Agent Hub automation profiles."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.models import AutomationProfile

logger = logging.getLogger(__name__)

_VALID_PAYLOAD_TYPES = frozenset({"agent_turn", "push", "self_honing", "memory_review"})
_PERSONA_WORKFLOW_KEY = "agent-hub.persona_job"
_AUTOMATIONS_URL = "/automations?project_id=agent-hub"


async def schedule_job(
    name: str,
    schedule_type: str,
    schedule_value: str,
    payload_message: str,
    payload_type: str = "agent_turn",
    delivery: str = "none",
    timezone: str = "UTC",
) -> str:
    """Create a centrally managed persona automation."""
    if schedule_type not in ("at", "every", "cron"):
        return f"Error: Invalid schedule_type '{schedule_type}'. Must be at/every/cron."
    if payload_type not in _VALID_PAYLOAD_TYPES:
        return (
            f"Error: Invalid payload_type '{payload_type}'. "
            "Must be agent_turn/push/self_honing/memory_review."
        )

    try:
        from app.db import async_session
        from app.services import automations
        from app.services.persona_service import get_or_create_persona
        from app.workflows.persona_scheduler import compute_next_run

        next_run = compute_next_run(schedule_type, schedule_value, timezone)
        if next_run is None and schedule_type == "at":
            return "Error: Scheduled time is in the past."

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            await automations.import_agent_hub_legacy(db)
            profile = await automations.create_profile(
                db,
                {
                    "project_id": "agent-hub",
                    "subject_id": f"persona:{persona.id}",
                    "workflow_key": _PERSONA_WORKFLOW_KEY,
                    "label": name,
                    "schedule_type": schedule_type,
                    "schedule_value": schedule_value,
                    "schedule_timezone": timezone,
                    "config": {
                        "payload_type": payload_type,
                        "payload_message": payload_message,
                        "delivery": delivery,
                    },
                    "enabled": True,
                },
                changed_by="agent:persona",
            )
            profile_id = profile.id
            scheduled_for = profile.next_run_at
            await db.commit()

        next_str = scheduled_for.isoformat() if scheduled_for else "N/A"
        return f"Job '{name}' scheduled (profile id={profile_id}). Next run: {next_str}"
    except Exception as exc:
        logger.exception("schedule_job failed")
        return f"Error scheduling job: {exc}"


async def list_scheduled_jobs(include_disabled: bool = False) -> str:
    """List persona jobs from the canonical automation profiles."""
    try:
        from app.db import async_session
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            query = select(AutomationProfile).where(
                AutomationProfile.project_id == "agent-hub",
                AutomationProfile.workflow_key == _PERSONA_WORKFLOW_KEY,
                AutomationProfile.subject_id == f"persona:{persona.id}",
            )
            if not include_disabled:
                query = query.where(AutomationProfile.enabled.is_(True))
            query = query.order_by(AutomationProfile.next_run_at)
            profiles = (await db.execute(query)).scalars().all()
            rows = [
                (
                    profile.id, profile.source_ref, profile.label, profile.schedule_type,
                    profile.schedule_value, (profile.config or {}).get("payload_type"),
                    profile.next_run_at, profile.run_count, profile.max_runs, profile.enabled,
                )
                for profile in profiles
            ]

        if not rows:
            return "(No scheduled jobs)"

        lines = []
        for profile_id, source_ref, name, schedule_type, schedule_value, payload_type, next_run, run_count, max_runs, enabled in rows:
            status = "enabled" if enabled else "disabled"
            next_str = next_run.isoformat() if next_run else "N/A"
            runs = str(run_count or 0)
            if max_runs:
                runs += f"/{max_runs}"
            legacy_id = source_ref.split(":", 1)[1] if source_ref and source_ref.startswith("persona:") else None
            legacy_text = f" legacy_job_id={legacy_id}" if legacy_id else ""
            lines.append(
                f"- **{name}** (profile id={profile_id}{legacy_text})\n"
                f"  {schedule_type}={schedule_value} | type={payload_type} | "
                f"next={next_str} | runs={runs} | {status}"
            )

        return "\n".join(lines)
    except Exception as exc:
        logger.exception("list_scheduled_jobs failed")
        return f"Error listing jobs: {exc}"


async def cancel_scheduled_job(job_id: str, hard_delete: bool = False) -> str:
    """Disable a centrally managed persona profile by profile or legacy job ID."""
    if hard_delete:
        return (
            "Error: Permanent deletion is unavailable. Disable the profile in "
            f"{_AUTOMATIONS_URL} or use st automations disable <profile-id>."
        )

    try:
        from app.db import async_session
        from app.services import automations
        from app.services.persona_service import get_or_create_persona

        async with async_session() as db:
            persona = await get_or_create_persona(db)
            subject_id = f"persona:{persona.id}"
            profile = await db.get(AutomationProfile, job_id)
            if profile is None:
                profile = (await db.execute(select(AutomationProfile).where(
                    AutomationProfile.project_id == "agent-hub",
                    AutomationProfile.workflow_key == _PERSONA_WORKFLOW_KEY,
                    AutomationProfile.subject_id == subject_id,
                    AutomationProfile.source_ref == f"persona:{job_id}",
                ))).scalar_one_or_none()
            if (
                profile is None
                or profile.project_id != "agent-hub"
                or profile.workflow_key != _PERSONA_WORKFLOW_KEY
                or profile.subject_id != subject_id
            ):
                return f"Error: Job '{job_id}' not found."

            name = profile.label
            await automations.update_profile(
                db,
                profile.id,
                {"enabled": False, "expected_revision": profile.revision},
                changed_by="agent:persona",
            )
            await db.commit()
            return f"Job '{name}' (profile id={profile.id}) disabled."
    except Exception as exc:
        logger.exception("cancel_scheduled_job failed")
        return f"Error cancelling job: {exc}"
