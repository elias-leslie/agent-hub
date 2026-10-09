"""Authenticated canonical Automations API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.access_control_auth import require_service_client
from app.models import (
    AutomationDefinition,
    AutomationProfile,
    AutomationProfileRevision,
    AutomationRun,
    PersonaScheduledJob,
)
from app.models.client import check_project_access
from app.services import automations as service

router = APIRouter(prefix="/automations", tags=["automations"])


class ProfileCreate(BaseModel):
    project_id: str
    workflow_key: str
    subject_id: str | None = None
    label: str | None = None
    schedule_type: str
    schedule_value: str
    schedule_timezone: str = "UTC"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class ProfilePatch(BaseModel):
    expected_revision: int
    subject_id: str | None = None
    label: str | None = None
    schedule_type: str | None = None
    schedule_value: str | None = None
    schedule_timezone: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class PolicyPut(BaseModel):
    expected_revision: int
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    idempotency_key: str | None = None


class AcceptRequest(BaseModel):
    owner_run_id: str
    receipt: dict[str, Any] = Field(default_factory=dict)


class CompleteRequest(BaseModel):
    status: str
    owner_run_id: str | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ProfileImport(ProfileCreate):
    enabled: bool
    source_ref: str
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    run_count: int = Field(default=0, ge=0)
    max_runs: int | None = Field(default=None, ge=1)
    owner_gate_reasons: list[str] = Field(default_factory=list)
    imported_unreviewed_count: int = Field(default=0, ge=0)


class CutoverRequest(BaseModel):
    expected_revision: int
    fence_receipt: str = Field(min_length=1)
    next_run_at: datetime | None = None


class ReviewRequest(BaseModel):
    through_run_id: str | None = None


def _actor(request: Request) -> str:
    return str(getattr(request.state, "request_source", None) or "automations-api")


def _definition(row: AutomationDefinition) -> dict[str, Any]:
    config_schema = row.config_schema
    if row.workflow_key == "agent-hub.persona_heartbeat":
        config_schema = {
            **config_schema,
            "properties": {
                key: value for key, value in config_schema.get("properties", {}).items()
                if key != "execution_state"
            },
        }
    return {
        "workflow_key": row.workflow_key, "version": row.version,
        "owner_project_id": row.owner_project_id, "label": row.label,
        "description": row.description, "dispatch_kind": row.dispatch_kind,
        "dispatch_target": row.dispatch_target,
        "config_schema": config_schema, "policy_schema": row.policy_schema,
        "default_schedule": row.default_schedule, "default_enabled": row.default_enabled,
        "manual_when_disabled": row.manual_when_disabled,
        "manual_advances_cursor": row.manual_advances_cursor,
        "overlap_strategy": row.overlap_strategy,
    }


def _policy(row: Any) -> dict[str, Any]:
    return {
        "project_id": row.project_id, "enabled": row.enabled,
        "config": row.config or {}, "revision": row.revision,
        "sync_revision": row.sync_revision,
        "sync_pending": service.policy_sync_pending(row),
        "updated_by": row.updated_by, "updated_at": row.updated_at,
    }


async def _profile(db: AsyncSession, row: AutomationProfile) -> dict[str, Any]:
    policy = await service.get_policy(db, row.project_id)
    definition = await db.get(AutomationDefinition, (row.workflow_key, row.definition_version))
    if definition is None:
        raise HTTPException(status_code=409, detail="Registered definition version is missing")
    owner_reasons = await service.live_owner_gate_reasons(db, row)
    gates = service.effective_gate_reasons(
        profile_enabled=row.enabled, policy_enabled=policy.enabled,
        owner_gate_reasons=owner_reasons,
        manual=False, manual_when_disabled=definition.manual_when_disabled,
    )
    gates.extend(service.policy_profile_gate_reasons(row.workflow_key, policy))
    if row.clock_owner == "legacy":
        gates.append("legacy_clock_owner")
    unreviewed = await db.scalar(select(func.count()).select_from(AutomationRun).where(
        AutomationRun.profile_id == row.id,
        AutomationRun.created_at > (row.last_reviewed_at or datetime.min.replace(tzinfo=UTC)),
    ))
    config = row.config or {}
    if row.workflow_key == "agent-hub.persona_heartbeat":
        config = {key: value for key, value in config.items() if key != "execution_state"}
    return {
        "id": row.id, "project_id": row.project_id, "subject_id": row.subject_id,
        "workflow_key": row.workflow_key, "definition_version": row.definition_version,
        "label": row.label, "owner_project_id": definition.owner_project_id,
        "schedule_type": row.schedule_type, "schedule_value": row.schedule_value,
        "schedule_timezone": row.schedule_timezone, "config": config,
        "enabled": row.enabled, "effective_enabled": not gates or gates == ["legacy_clock_owner"],
        "gate_reasons": gates, "clock_owner": row.clock_owner,
        "next_run_at": row.next_run_at, "last_run_at": row.last_run_at,
        "run_count": row.run_count, "max_runs": row.max_runs,
        "revision": row.revision,
        "unreviewed_count": int(unreviewed or 0) + int(row.imported_unreviewed_count or 0),
        "last_reviewed_at": row.last_reviewed_at,
    }


def _run(row: AutomationRun) -> dict[str, Any]:
    return {
        "id": row.id, "run_id": row.id, "profile_id": row.profile_id,
        "project_id": row.project_id, "workflow_key": row.workflow_key,
        "definition_version": row.definition_version,
        "profile_revision": row.profile_revision, "trigger": row.trigger,
        "occurrence_key": row.occurrence_key, "scheduled_for": row.scheduled_for,
        "status": row.status, "admitted": row.status != "rejected",
        "gate_reasons": row.gate_reasons or [], "owner_run_id": row.owner_run_id,
        "config_snapshot": row.config_snapshot or {},
        "policy_snapshot": row.policy_snapshot or {},
        "owner_receipt": row.owner_receipt or {}, "error": row.error,
        "requested_by": row.requested_by, "created_at": row.created_at,
        "accepted_at": row.accepted_at, "completed_at": row.completed_at,
    }


def _bad_command(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=f"Unknown automation: {exc.args[0]}")
    if isinstance(exc, service.RevisionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/registry")
async def list_registry(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    await service.import_agent_hub_legacy(db)
    await db.commit()
    rows = (await db.execute(select(AutomationDefinition).order_by(
        AutomationDefinition.owner_project_id, AutomationDefinition.workflow_key,
        AutomationDefinition.version.desc(),
    ))).scalars().all()
    return {"definitions": [_definition(row) for row in rows]}


@router.post("/profiles/validate")
async def validate_profile(
    payload: dict[str, Any], db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if payload.get("id"):
        profile = await db.get(AutomationProfile, payload["id"])
        if profile is None:
            return _invalid("unknown profile")
        full = {**service.profile_snapshot(profile), **payload}
    else:
        full = payload
    if not full.get("workflow_key"):
        return _invalid("workflow_key is required")
    try:
        definition = await service.get_definition(db, full["workflow_key"])
    except KeyError:
        return _invalid("unknown workflow")
    try:
        service.reject_persona_runtime_config_write(definition.workflow_key, payload)
        normalized = service.validate_profile_payload(full, definition)
        if not payload.get("id"):
            service.ensure_future_one_time(normalized, datetime.now(UTC))
    except service.AutomationValidationError as exc:
        # Report only the message the validator wrote, never an arbitrary exception's text.
        message = exc.args[0] if exc.args and isinstance(exc.args[0], str) else "invalid profile"
        return _invalid(message)
    return {"valid": True, "normalized": normalized, "errors": []}


def _invalid(message: str) -> dict[str, Any]:
    return {"valid": False, "normalized": None, "errors": [message]}


@router.get("/projects/{project_id}/policy")
async def get_project_policy(
    project_id: str, db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await service.get_policy(db, project_id)
    await db.commit()
    await db.refresh(row)
    return _policy(row)


@router.put("/projects/{project_id}/policy")
async def put_project_policy(
    project_id: str, payload: PolicyPut, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    try:
        row = await service.update_policy(
            db, project_id, enabled=payload.enabled, config=payload.config,
            expected_revision=payload.expected_revision, changed_by=_actor(request),
        )
    except (service.AutomationValidationError, service.RevisionConflict) as exc:
        raise _bad_command(exc) from exc
    await db.commit()
    if project_id == "jobinator-4000":
        from app.services.automation_dispatch import sync_jobinator_policy

        await sync_jobinator_policy()
    await db.refresh(row)
    return _policy(row)


@router.get("/profiles")
async def list_profiles(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: str | None = None, limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    await service.import_agent_hub_legacy(db)
    await db.commit()
    query = select(AutomationProfile)
    if project_id:
        query = query.where(AutomationProfile.project_id == project_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(
        AutomationProfile.project_id, AutomationProfile.label
    ).limit(limit).offset(offset))).scalars().all()
    return {"items": [await _profile(db, row) for row in rows], "total": total or 0}


@router.post("/profiles", status_code=201)
async def post_profile(
    payload: ProfileCreate, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    try:
        row = await service.create_profile(db, payload.model_dump(), changed_by=_actor(request))
    except (KeyError, service.AutomationValidationError) as exc:
        raise _bad_command(exc) from exc
    await db.commit()
    return await _profile(db, row)


@router.get("/profiles/{profile_id}")
async def get_profile(
    profile_id: str, db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(AutomationProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return await _profile(db, row)


@router.patch("/profiles/{profile_id}")
async def patch_profile(
    profile_id: str, payload: ProfilePatch, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    updates = payload.model_dump(exclude_unset=True)
    try:
        row = await service.update_profile(db, profile_id, updates, changed_by=_actor(request))
    except (KeyError, service.AutomationValidationError, service.RevisionConflict) as exc:
        raise _bad_command(exc) from exc
    await db.commit()
    return await _profile(db, row)


@router.post("/profiles/{profile_id}/run", status_code=202)
async def run_profile(
    profile_id: str, payload: RunRequest, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    try:
        row = await service.admit_run(
            db, profile_id, trigger="manual", idempotency_key=payload.idempotency_key,
            requested_by=_actor(request),
        )
    except KeyError as exc:
        raise _bad_command(exc) from exc
    await db.commit()
    if row.status == "admitted":
        from app.services.automation_dispatch import dispatch_run
        await dispatch_run(row.id)
        await db.refresh(row)
    return _run(row)


@router.post("/profiles/{profile_id}/review")
async def review_profile(
    profile_id: str, db: Annotated[AsyncSession, Depends(get_db)],
    payload: ReviewRequest | None = None,
) -> dict[str, Any]:
    row = await db.get(AutomationProfile, profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    if payload and payload.through_run_id:
        through = await db.get(AutomationRun, payload.through_run_id)
        if through is None or through.profile_id != profile_id:
            raise HTTPException(status_code=404, detail="Review run not found for profile")
        row.last_reviewed_at = through.created_at
    else:
        row.last_reviewed_at = datetime.now(UTC)
    row.imported_unreviewed_count = 0
    await db.commit()
    return await _profile(db, row)


@router.get("/runs")
async def list_runs(
    db: Annotated[AsyncSession, Depends(get_db)],
    profile_id: str | None = None, project_id: str | None = None,
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    query = select(AutomationRun)
    if profile_id:
        query = query.where(AutomationRun.profile_id == profile_id)
    if project_id:
        query = query.where(AutomationRun.project_id == project_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(
        AutomationRun.created_at.desc()
    ).limit(limit).offset(offset))).scalars().all()
    return {"items": [_run(row) for row in rows], "total": total or 0}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str, db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = await db.get(AutomationRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run(row)


async def _require_owner(db: AsyncSession, request: Request, run: AutomationRun) -> None:
    client = await require_service_client(request)
    definition = await db.get(AutomationDefinition, (run.workflow_key, run.definition_version))
    if definition is None or (
        client.get("client_type") not in {"internal", "service"}
        or client.get("allowed_projects") is None
        or not check_project_access(client["allowed_projects"], definition.owner_project_id)
    ):
        raise HTTPException(status_code=403, detail="Run owner mismatch")


async def _require_project_owner(request: Request, project_id: str) -> None:
    client = await require_service_client(request)
    if (
        client.get("client_type") not in {"internal", "service"}
        or client.get("allowed_projects") is None
        or not check_project_access(client["allowed_projects"], project_id)
    ):
        raise HTTPException(status_code=403, detail="Project owner mismatch")


@router.post("/profiles/import")
async def import_profile(
    payload: ProfileImport, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Owner-attested cursor and gate import; never switches the execution clock."""
    await _require_project_owner(request, payload.project_id)
    try:
        definition = await service.get_definition(db, payload.workflow_key)
        service.reject_persona_runtime_config_write(definition.workflow_key, payload.model_dump())
        data = service.validate_profile_payload(payload.model_dump(), definition)
    except (KeyError, service.AutomationValidationError) as exc:
        raise _bad_command(exc) from exc
    row = (await db.execute(select(AutomationProfile).where(
        AutomationProfile.source_ref == payload.source_ref
    ).with_for_update())).scalar_one_or_none()
    created = row is None
    previous = service.profile_snapshot(row) if row is not None else None
    if row is not None and row.clock_owner != "legacy":
        raise HTTPException(status_code=409, detail="Profile clock already transferred")
    if row is None:
        row = AutomationProfile(
            id=str(uuid4()), project_id=payload.project_id,
            workflow_key=payload.workflow_key, definition_version=definition.version,
            source_ref=payload.source_ref, clock_owner="legacy", revision=1,
        )
        db.add(row)
    elif row.project_id != payload.project_id or row.workflow_key != payload.workflow_key:
        raise HTTPException(status_code=409, detail="Source reference already belongs to another profile")
    row.subject_id = payload.subject_id
    row.label = payload.label or definition.label
    row.schedule_type = data["schedule_type"]
    row.schedule_value = data["schedule_value"]
    row.schedule_timezone = data["schedule_timezone"]
    row.config = data["config"]
    row.enabled = payload.enabled
    row.next_run_at = payload.next_run_at
    row.last_run_at = payload.last_run_at
    row.run_count = payload.run_count
    row.max_runs = payload.max_runs
    row.owner_gate_reasons = payload.owner_gate_reasons
    row.imported_unreviewed_count = payload.imported_unreviewed_count
    if created:
        await db.flush()
        db.add(AutomationProfileRevision(
            id=str(uuid4()), profile_id=row.id, revision=1,
            snapshot=service.profile_snapshot(row), changed_by=_actor(request),
        ))
    elif previous != service.profile_snapshot(row):
        row.revision += 1
        db.add(AutomationProfileRevision(
            id=str(uuid4()), profile_id=row.id, revision=row.revision,
            snapshot=service.profile_snapshot(row), changed_by=_actor(request),
        ))
    await db.commit()
    return await _profile(db, row)


@router.post("/profiles/{profile_id}/cutover")
async def cutover_profile(
    profile_id: str, payload: CutoverRequest, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Transfer the clock only after the authenticated owner records its fence."""
    row = (await db.execute(select(AutomationProfile).where(
        AutomationProfile.id == profile_id
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    await _require_project_owner(request, row.project_id)
    if row.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="Profile revision has changed")
    if row.clock_owner == "central":
        return await _profile(db, row)
    if row.project_id == "jobinator-4000":
        policy = await service.get_policy(db, row.project_id)
        if not {"screening_cap", "classification_cap"}.issubset(policy.config or {}):
            raise HTTPException(status_code=409, detail="Jobinator shared quota policy is not imported")
        if service.policy_sync_pending(policy):
            raise HTTPException(status_code=409, detail="Jobinator shared quota policy awaits owner sync")
    row.clock_owner = "central"
    if row.project_id == "agent-hub" and row.source_ref and row.source_ref.startswith("persona:"):
        job = await db.get(PersonaScheduledJob, row.source_ref.split(":", 1)[1])
        if job is not None:
            job.enabled = False
            job.next_run_at = None
    if payload.next_run_at is not None:
        row.next_run_at = payload.next_run_at
    elif row.project_id == "agent-hub" and row.source_ref and row.source_ref.startswith("static:"):
        row.next_run_at = service.next_due(
            row.schedule_type, row.schedule_value, row.schedule_timezone, datetime.now(UTC)
        )
    row.revision += 1
    db.add(AutomationProfileRevision(
        id=str(uuid4()), profile_id=row.id, revision=row.revision,
        snapshot={**service.profile_snapshot(row), "fence_receipt": payload.fence_receipt},
        changed_by=_actor(request),
    ))
    await db.commit()
    return await _profile(db, row)


@router.post("/runs/{run_id}/accept")
async def accept_run(
    run_id: str, payload: AcceptRequest, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    row = (await db.execute(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _require_owner(db, request, row)
    if row.owner_run_id and row.owner_run_id != payload.owner_run_id:
        raise HTTPException(status_code=409, detail="Run already accepted by another owner execution")
    if row.status not in {"admitted", "dispatching", "dispatched", "accepted", "running"}:
        raise HTTPException(status_code=409, detail="Run cannot be accepted in current status")
    row.owner_run_id = payload.owner_run_id
    row.owner_receipt = payload.receipt
    row.status = "accepted"
    row.accepted_at = row.accepted_at or datetime.now(UTC)
    await db.commit()
    return _run(row)


@router.post("/runs/{run_id}/complete")
async def complete_run(
    run_id: str, payload: CompleteRequest, request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    if payload.status not in {"succeeded", "failed", "skipped", "cancelled"}:
        raise HTTPException(status_code=422, detail="Invalid terminal status")
    row = (await db.execute(select(AutomationRun).where(AutomationRun.id == run_id).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    await _require_owner(db, request, row)
    if row.owner_run_id and payload.owner_run_id and row.owner_run_id != payload.owner_run_id:
        raise HTTPException(status_code=409, detail="Owner receipt mismatch")
    if row.status in {"succeeded", "failed", "skipped", "cancelled"}:
        if row.status != payload.status:
            raise HTTPException(status_code=409, detail="Run already completed with another status")
        return _run(row)
    row.owner_run_id = payload.owner_run_id or row.owner_run_id
    row.owner_receipt = payload.receipt
    row.error = payload.error
    row.status = payload.status
    row.completed_at = datetime.now(UTC)
    await db.commit()
    return _run(row)
