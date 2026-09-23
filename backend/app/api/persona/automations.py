"""Persona automation API over the existing scheduled-job model."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.automation_guidance import automation_moved
from app.db import get_db
from app.models.persona_scheduled_job import PersonaScheduledJob
from app.services.persona_service import get_or_create_persona

from .schemas import PersonaAutomationResponse

router = APIRouter()


def _job_to_response(job: PersonaScheduledJob) -> PersonaAutomationResponse:
    return PersonaAutomationResponse(
        id=job.id,
        name=job.name,
        schedule_type=job.schedule_type,
        schedule_value=job.schedule_value,
        schedule_timezone=job.schedule_timezone,
        payload_type=job.payload_type,
        payload_message=job.payload_message,
        payload_title=job.payload_title,
        delivery=job.delivery,
        enabled=bool(job.enabled),
        last_run_at=job.last_run_at.isoformat() if job.last_run_at else None,
        next_run_at=job.next_run_at.isoformat() if job.next_run_at else None,
        run_count=int(job.run_count or 0),
        max_runs=job.max_runs,
        created_at=job.created_at.isoformat() if job.created_at else None,
    )


@router.get("/automations", response_model=list[PersonaAutomationResponse])
async def list_automations(
    db: AsyncSession = Depends(get_db),
) -> list[PersonaAutomationResponse]:
    """List persona-owned scheduled automations."""
    persona = await get_or_create_persona(db)
    result = await db.execute(
        select(PersonaScheduledJob)
        .where(PersonaScheduledJob.persona_id == persona.id)
        .order_by(PersonaScheduledJob.enabled.desc(), PersonaScheduledJob.next_run_at.asc())
    )
    jobs = result.scalars().all()
    return [_job_to_response(job) for job in jobs]


@router.post("/automations")
async def create_automation() -> None:
    """Retired writer; central Automations owns persona schedules."""
    raise automation_moved()


@router.patch("/automations/{job_id}")
async def update_automation(job_id: str) -> None:
    """Retired writer; central Automations owns persona schedules."""
    raise automation_moved()


@router.delete("/automations/{job_id}")
async def delete_automation(job_id: str) -> None:
    """Retired writer; central Automations owns persona schedules."""
    raise automation_moved()


@router.post("/automations/{job_id}/trigger")
async def trigger_automation(job_id: str) -> None:
    """Retired writer; run profiles from central Automations."""
    raise automation_moved()
