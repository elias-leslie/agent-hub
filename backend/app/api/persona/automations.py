"""Persona automation API over the existing scheduled-job model."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.persona_scheduled_job import PersonaScheduledJob
from app.services.persona_service import get_or_create_persona
from app.workflows.persona_scheduler import (
    _maybe_send_delivery_push,
    _maybe_send_delivery_telegram,
    compute_next_run,
    execute_job,
)

from .schemas import (
    PersonaAutomationCreate,
    PersonaAutomationResponse,
    PersonaAutomationTriggerResponse,
    PersonaAutomationUpdate,
)

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


async def _require_job(
    db: AsyncSession,
    persona_id: int,
    job_id: str,
) -> PersonaScheduledJob:
    result = await db.execute(
        select(PersonaScheduledJob).where(
            PersonaScheduledJob.persona_id == persona_id,
            PersonaScheduledJob.id == job_id,
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Automation '{job_id}' not found")
    return job


def _compute_or_422(
    schedule_type: str,
    schedule_value: str,
    schedule_timezone: str,
    *,
    last_run_at: datetime | None = None,
) -> tuple[datetime | None, int | None]:
    next_run = compute_next_run(
        schedule_type,
        schedule_value,
        schedule_timezone,
        last_run_at=last_run_at,
    )
    if schedule_type == "at" and next_run is None:
        raise HTTPException(status_code=422, detail="Scheduled time is in the past")
    max_runs = 1 if schedule_type == "at" else None
    return next_run, max_runs


def _validate_delivery_or_422(*, payload_type: str, delivery: str) -> None:
    if delivery == "telegram" and payload_type != "agent_turn":
        raise HTTPException(status_code=422, detail="delivery=telegram requires payload_type=agent_turn")


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


@router.post("/automations", response_model=PersonaAutomationResponse, status_code=201)
async def create_automation(
    payload: PersonaAutomationCreate,
    db: AsyncSession = Depends(get_db),
) -> PersonaAutomationResponse:
    """Create one persona automation without adding new runtime tools."""
    persona = await get_or_create_persona(db)
    next_run, max_runs = _compute_or_422(
        payload.schedule_type,
        payload.schedule_value,
        payload.schedule_timezone,
    )
    _validate_delivery_or_422(payload_type=payload.payload_type, delivery=payload.delivery)
    job = PersonaScheduledJob(
        persona_id=persona.id,
        name=payload.name,
        schedule_type=payload.schedule_type,
        schedule_value=payload.schedule_value,
        schedule_timezone=payload.schedule_timezone,
        payload_type=payload.payload_type,
        payload_message=payload.payload_message,
        payload_title=payload.payload_title,
        delivery=payload.delivery,
        enabled=payload.enabled,
        next_run_at=next_run,
        max_runs=max_runs,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _job_to_response(job)


@router.patch("/automations/{job_id}", response_model=PersonaAutomationResponse)
async def update_automation(
    job_id: str,
    payload: PersonaAutomationUpdate,
    db: AsyncSession = Depends(get_db),
) -> PersonaAutomationResponse:
    """Patch one persona automation."""
    persona = await get_or_create_persona(db)
    job = await _require_job(db, persona.id, job_id)
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        return _job_to_response(job)

    for field, value in updates.items():
        setattr(job, field, value)

    _validate_delivery_or_422(payload_type=job.payload_type, delivery=job.delivery)

    if {
        "schedule_type",
        "schedule_value",
        "schedule_timezone",
        "enabled",
    } & updates.keys():
        next_run, max_runs = _compute_or_422(
            job.schedule_type,
            job.schedule_value,
            job.schedule_timezone,
            last_run_at=job.last_run_at,
        )
        job.max_runs = max_runs
        job.next_run_at = next_run if job.enabled else None

    await db.commit()
    await db.refresh(job)
    return _job_to_response(job)


@router.delete("/automations/{job_id}", status_code=204)
async def delete_automation(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete one persona automation."""
    persona = await get_or_create_persona(db)
    job = await _require_job(db, persona.id, job_id)
    await db.delete(job)
    await db.commit()
    return Response(status_code=204)


@router.post("/automations/{job_id}/trigger", response_model=PersonaAutomationTriggerResponse)
async def trigger_automation(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> PersonaAutomationTriggerResponse:
    """Run one automation immediately and surface any created session id."""
    persona = await get_or_create_persona(db)
    job = await _require_job(db, persona.id, job_id)
    result = await execute_job(job)
    await _maybe_send_delivery_push(job, result.output)
    await _maybe_send_delivery_telegram(job, result.output)
    now = datetime.now(UTC)
    job.last_run_at = now
    job.run_count = int(job.run_count or 0) + 1
    if job.enabled:
        job.next_run_at = compute_next_run(
            job.schedule_type,
            job.schedule_value,
            job.schedule_timezone,
            last_run_at=now,
        )
        if job.max_runs is not None and job.run_count >= job.max_runs:
            job.enabled = False
            job.next_run_at = None
    else:
        job.next_run_at = None
    await db.commit()
    await db.refresh(job)
    return PersonaAutomationTriggerResponse(
        job=_job_to_response(job),
        output=result.output,
        session_id=result.session_id,
        triggered_at=now.isoformat(),
    )
