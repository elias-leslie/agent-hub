"""Durable technical recovery dispatch for context maintenance items.

This module only creates and observes the corresponding SummitFlow task.  A
successful task is evidence that technical work ran; the maintenance item
stays pending until the canonical context queue is revalidated.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.context_governance import ContextMaintenanceItem
from app.services.context_maintenance import ACTIVE_STATES, maintenance_event
from app.services.project_permission_service import check_execution_permission

_SUMMITFLOW_PROJECT = "summitflow"
_TASK_PROJECT = "agent-hub"
_EXTERNAL_ORIGIN = "agent-hub-context-maintenance"
_CANONICAL_GUIDANCE = (
    "Inspect the retained Agent Hub context-maintenance item and its evidence IDs. "
    "Use canonical maintenance inspect/claim/apply/dismiss actions, preserve exact "
    "source revisions. Completing a SummitFlow task alone does not resolve the item; "
    "a verified canonical correction may resolve it with its retained receipt."
)
_ACTIVE_TASK_STATUSES = frozenset({"pending", "running", "paused"})
_EXECUTION_GATED_TASK_STATUSES = frozenset({"pending", "paused"})
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "abandoned", "closed", "archived"})
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429})
_PICKUP_SCHEDULE_ID = "work_pickup"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _mark_detail_changed(item: ContextMaintenanceItem) -> None:
    # Unit tests use lightweight stand-ins; real ORM rows need the explicit
    # JSON marker after nested technical_work mutations.
    with suppress(Exception):
        flag_modified(item, "detail")


def _receipt(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only stable task identity/status fields in the maintenance receipt."""
    return {
        key: payload[key]
        for key in (
            "id",
            "status",
            "project_id",
            "archived",
            "external_origin",
            "external_request_key",
            "external_payload_digest",
            "completed_at",
            "updated_at",
        )
        if key in payload
    }


def _diagnosis(item: ContextMaintenanceItem) -> dict[str, Any]:
    """Build a task packet without copying source text or model packets."""
    return {
        "maintenance_item_id": item.id,
        "kind": item.kind,
        "summary": str(item.summary or ""),
        "recommendation": str(item.recommendation or ""),
        "source_ids": sorted(str(value) for value in (item.source_keys or [])),
        "evidence_ids": sorted(str(value) for value in (item.evidence_ids or [])),
    }


def _generation(item: ContextMaintenanceItem) -> int:
    value = (item.detail or {}).get("generation", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _external_request_key(item: ContextMaintenanceItem) -> str:
    generation = _generation(item)
    return item.id if generation == 0 else f"{item.id}:generation-{generation}"


def _build_request(item: ContextMaintenanceItem, *, reason: str) -> dict[str, Any]:
    diagnosis = _diagnosis(item)
    kind_title = str(item.kind or "maintenance").replace("_", " ").capitalize()
    external_request_key = _external_request_key(item)
    return {
        "title": f"Context maintenance recovery: {kind_title}",
        "external_origin": _EXTERNAL_ORIGIN,
        "external_request_key": external_request_key,
        "description": (
            f"{_CANONICAL_GUIDANCE}\n\nDiagnosis: {diagnosis['summary']}"
            f"\nReason for dispatch: {reason}"
        ),
        "objective": "Resolve or clarify one canonical context-maintenance finding.",
        "constraints": [
            "Do not include or copy source contents into the task.",
            "Keep repairs scoped to the finding and preserve unrelated work. Verify any necessary canonical replacement before retiring or weakening an existing source.",
        ],
        "done_when": [
            "Inspect the exact maintenance item and retained evidence.",
            "Use canonical maintenance actions for any supported correction.",
            "Record the observed receipt; canonical queue revalidation decides resolution.",
        ],
        "labels": ["agent-hub", "context-maintenance", "technical-recovery"],
        "task_type": "bug",
        "execution_mode": "autonomous",
        "auto_dispatch": True,
        "ai_review": True,
        "references": [
            f"agent-hub:context-maintenance:{item.id}",
            *diagnosis["source_ids"],
            *diagnosis["evidence_ids"],
        ],
    }


async def _save_event(db: AsyncSession, item: ContextMaintenanceItem, action: str, evidence: dict[str, Any]) -> None:
    if item.state in ACTIVE_STATES:
        item.version += 1
    _mark_detail_changed(item)
    await maintenance_event(db, item, "system:context-maintenance", action, evidence)
    await db.commit()


def _work_projection(work: dict[str, Any]) -> dict[str, Any]:
    """Ignore observation timestamps when deciding whether to append history."""
    projection = {key: value for key, value in work.items() if key != "observed_at"}
    receipt = projection.get("receipt")
    if isinstance(receipt, dict):
        projection["receipt"] = {key: value for key, value in receipt.items() if key != "updated_at"}
    return projection


def _same_completed_receipt(previous: Any, current: dict[str, Any]) -> bool:
    if not isinstance(previous, dict):
        return False
    keys = ("id", "status", "completed_at", "updated_at")
    return all(previous.get(key) == current.get(key) for key in keys)


async def _execution_permission(db: AsyncSession) -> dict[str, Any]:
    """Return the local project execution gate without changing its policy."""
    permission = await check_execution_permission(db, _TASK_PROJECT)
    return {
        "allowed": bool(permission.allowed),
        "permission_tier": str(permission.permission_tier),
        "auto_exec_enabled": bool(permission.auto_exec_enabled),
        "in_time_window": bool(permission.in_time_window),
        "reason": str(permission.reason),
    }


async def _read_pickup_schedule(client: httpx.AsyncClient, api_base: str) -> dict[str, Any]:
    """Read SummitFlow's pickup schedule and its optional task filters."""
    endpoint = f"{api_base.rstrip('/')}/projects/{_TASK_PROJECT}/autonomous/schedules"
    try:
        response = await client.get(endpoint)
        if response.status_code >= 400:
            return {
                "available": False,
                "reason": f"summitflow_pickup_status_http_{response.status_code}",
            }
        payload = response.json()
    except Exception as exc:
        return {"available": False, "reason": f"summitflow_pickup_status_{type(exc).__name__}"}
    if not isinstance(payload, list):
        return {"available": False, "reason": "summitflow_pickup_status_malformed"}
    schedule = next(
        (entry for entry in payload if isinstance(entry, dict) and entry.get("schedule_id") == _PICKUP_SCHEDULE_ID),
        None,
    )
    if schedule is None:
        return {"available": False, "reason": "summitflow_pickup_schedule_missing"}
    enabled = bool(schedule.get("enabled"))
    result = {
        "available": True,
        "enabled": enabled,
        "reason": "allowed" if enabled else "work_pickup_disabled",
    }
    if not enabled:
        return result

    settings_endpoint = f"{api_base.rstrip('/')}/projects/{_TASK_PROJECT}/autonomous/settings"
    try:
        settings_response = await client.get(settings_endpoint)
        if settings_response.status_code >= 400:
            return {
                "available": False,
                "reason": f"summitflow_pickup_settings_http_{settings_response.status_code}",
            }
        settings = settings_response.json()
    except Exception as exc:
        return {"available": False, "reason": f"summitflow_pickup_settings_{type(exc).__name__}"}
    if not isinstance(settings, dict):
        return {"available": False, "reason": "summitflow_pickup_settings_malformed"}

    # These fields are optional for compatibility with older SummitFlow
    # deployments. When present, preserve explicit empty lists as deny-all.
    for field in ("allowed_types", "external_origins"):
        value = settings.get(field)
        if value is not None and not isinstance(value, list):
            return {"available": False, "reason": "summitflow_pickup_settings_malformed"}
        if isinstance(value, list):
            result[field] = [str(entry).strip() for entry in value if str(entry).strip()]
        else:
            result[field] = None
    return result


def _pickup_filter_reason(work: dict[str, Any], pickup: dict[str, Any]) -> str | None:
    """Return a canonical pickup-filter reason for one frozen task request."""
    if not pickup.get("available"):
        return str(pickup.get("reason") or "summitflow_pickup_status_unavailable")
    if not pickup.get("enabled"):
        return "work_pickup_disabled"
    request = work.get("request")
    request = request if isinstance(request, dict) else {}
    # Context-maintenance requests are frozen as ``bug`` tasks. Older rows
    # may predate the frozen request, so retain that canonical task type while
    # still applying a configured allowlist.
    task_type = str(request.get("task_type") or "bug")
    allowed_types = pickup.get("allowed_types")
    if isinstance(allowed_types, list) and task_type not in allowed_types:
        return "task_type_not_allowed"
    external_origin = str(request.get("external_origin") or _EXTERNAL_ORIGIN)
    allowed_origins = pickup.get("external_origins")
    if isinstance(allowed_origins, list) and external_origin not in allowed_origins:
        return "external_origin_not_allowed"
    return None


def _apply_execution_permission(
    detail: dict[str, Any],
    work: dict[str, Any],
    permission: dict[str, Any],
) -> bool:
    """Mark a queued task blocked by the gate, or clear only that block."""
    if not permission["allowed"]:
        work.update({
            "task_owned": False,
            "technical_blocked": True,
            "execution_permission_blocked": True,
            "execution_permission": permission,
        })
        detail.update({"technical_blocked": True, "handoff_needed": True})
        return True

    work.pop("execution_permission_blocked", None)
    work.pop("execution_permission", None)
    if work.get("pickup_schedule_blocked"):
        work.update({"task_owned": False, "technical_blocked": True})
    else:
        work.update({"task_owned": True, "technical_blocked": False})
        detail.update({"technical_blocked": False, "handoff_needed": False})
    return False


def _apply_pickup_schedule(
    detail: dict[str, Any],
    work: dict[str, Any],
    pickup: dict[str, Any],
) -> bool:
    """Mark queued work blocked when pickup is disabled, unreadable, or filtered."""
    reason = _pickup_filter_reason(work, pickup)
    if reason is not None:
        observed = dict(pickup)
        observed["reason"] = reason
        work.update({
            "task_owned": False,
            "technical_blocked": True,
            "pickup_schedule_blocked": True,
            "pickup_schedule": observed,
        })
        detail.update({"technical_blocked": True, "handoff_needed": True})
        return True

    work.pop("pickup_schedule_blocked", None)
    work.pop("pickup_schedule", None)
    if work.get("execution_permission_blocked"):
        work.update({"task_owned": False, "technical_blocked": True})
    else:
        work.update({"task_owned": True, "technical_blocked": False})
        detail.update({"technical_blocked": False, "handoff_needed": False})
    return False


def _clear_queued_gate_markers(work: dict[str, Any]) -> None:
    """Remove temporary queued-state gates once a task is running/terminal."""
    work.pop("execution_permission_blocked", None)
    work.pop("execution_permission", None)
    work.pop("pickup_schedule_blocked", None)
    work.pop("pickup_schedule", None)


async def _save_observation(
    db: AsyncSession,
    item: ContextMaintenanceItem,
    before_detail: dict[str, Any],
    action: str,
    evidence: dict[str, Any],
) -> None:
    before = dict(before_detail.get("technical_work") or {})
    after = dict((item.detail or {}).get("technical_work") or {})
    before_handoff = before_detail.get("handoff_needed")
    after_handoff = (item.detail or {}).get("handoff_needed")
    if _work_projection(before) == _work_projection(after) and before_handoff == after_handoff:
        item.detail = before_detail
        return
    await _save_event(db, item, action, evidence)


async def _project_api_url() -> str:
    from app.core.project_roots import ProjectRegistryUnavailable, get_registered_project_roots
    from app.workflows._heartbeat_project import _read_project_api_url

    try:
        roots = await get_registered_project_roots()
    except ProjectRegistryUnavailable:
        return ""
    root = roots.get(_SUMMITFLOW_PROJECT)
    if not root:
        return ""
    return await asyncio.to_thread(
        _read_project_api_url,
        _SUMMITFLOW_PROJECT,
        root=Path(root),
    )


async def dispatch_technical_work(
    db: AsyncSession,
    item: ContextMaintenanceItem,
    *,
    reason: str,
) -> dict[str, Any]:
    """Create or replay one idempotent SummitFlow technical recovery task."""
    detail = dict(item.detail or {})
    work = dict(detail.get("technical_work") or {})
    existing_status = str(work.get("status") or "")
    existing_task_id = work.get("task_id")
    if item.state not in ACTIVE_STATES:
        return {"status": existing_status or "closed", "task_id": existing_task_id, "created": False}
    if existing_task_id and existing_status == "completed":
        work.update({"status": "completed_pending_revalidation", "task_owned": False})
        item.detail = {**detail, "technical_work": work, "handoff_needed": True, "technical_blocked": False}
        await _save_event(db, item, "technical_work_completed", {"task_id": existing_task_id, "next": "pending_revalidation"})
        return {"status": "completed_pending_revalidation", "task_id": existing_task_id, "created": False}
    if existing_task_id or existing_status in {"blocked", "completed_pending_revalidation", "failed", "cancelled", "archived"}:
        return {"status": existing_status or "observed", "task_id": existing_task_id, "created": False}

    request = dict(work.get("request") or {})
    if not request:
        request = _build_request(item, reason=reason)
        generation = _generation(item)
        work = {
            "status": "dispatch_pending",
            "request": request,
            "external_origin": _EXTERNAL_ORIGIN,
            "external_request_key": request["external_request_key"],
            "task_id": None,
            "task_owned": True,
            "attempt_count": 0,
            "created_at": _now(),
            "generation": generation,
        }
    external_request_key = str(work.get("external_request_key") or request.get("external_request_key") or _external_request_key(item))
    work["external_request_key"] = external_request_key
    work["status"] = "dispatching"
    work["task_owned"] = True
    work["attempt_count"] = int(work.get("attempt_count") or 0) + 1
    detail.update({"technical_work": work, "handoff_needed": False})
    item.detail = detail
    await _save_event(db, item, "technical_work_dispatching", {
        "external_origin": _EXTERNAL_ORIGIN,
        "external_request_key": external_request_key,
        "attempt_count": work["attempt_count"],
    })

    api_base = await _project_api_url()
    if not api_base:
        work.update({"status": "dispatch_pending", "task_owned": False, "technical_blocked": True,
                     "error": "SummitFlow API URL unavailable", "observed_at": _now()})
        item.detail = {**item.detail, "technical_work": work, "technical_blocked": True}
        await _save_event(db, item, "technical_work_dispatch_failed", {"reason": work["error"]})
        return {"status": "dispatch_pending", "task_id": None, "created": False, "error": work["error"]}

    endpoint = f"{api_base.rstrip('/')}/projects/{_TASK_PROJECT}/tasks"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint, json=request)
        try:
            parsed = response.json()
        except Exception:
            parsed = {}
        body = parsed if isinstance(parsed, dict) else {}
        if response.status_code >= 400:
            error = str(body.get("detail") or body.get("error") or f"HTTP {response.status_code}")
            permanent = response.status_code < 500 and response.status_code not in _RETRYABLE_HTTP_STATUSES
            work.update({"status": "blocked" if permanent else "dispatch_pending", "task_owned": not permanent,
                         "technical_blocked": permanent, "error": error, "observed_at": _now()})
            item.detail = {**item.detail, "technical_work": work, "technical_blocked": permanent}
            await _save_event(db, item, "technical_work_blocked" if permanent else "technical_work_dispatch_failed", {"error": error, "status_code": response.status_code})
            return {"status": work["status"], "task_id": None, "created": False, "error": error}
        task_id = body.get("id") or body.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("SummitFlow response did not contain a task ID")
        work["task_id"] = task_id
        item.detail = {**item.detail, "technical_work": work}
        _mark_detail_changed(item)
        if hasattr(db, "flush"):
            await db.flush()
        task_status = str(body.get("status") or "pending")
        observed_status = "completed_pending_revalidation" if task_status == "completed" else task_status
        terminal_failure = observed_status in _TERMINAL_TASK_STATUSES or bool(body.get("archived"))
        if body.get("archived"):
            observed_status = "archived"
        work.update({"status": observed_status, "task_id": task_id, "task_owned": observed_status in _ACTIVE_TASK_STATUSES,
                     "receipt": _receipt(body), "observed_at": _now(), "error": None,
                     "generation": _generation(item)})
        permission: dict[str, Any] | None = None
        pickup: dict[str, Any] | None = None
        execution_blocked = False
        pickup_blocked = False
        if observed_status in _EXECUTION_GATED_TASK_STATUSES and not terminal_failure:
            permission = await _execution_permission(db)
            execution_blocked = _apply_execution_permission(item.detail, work, permission)
            async with httpx.AsyncClient(timeout=30.0) as client:
                pickup = await _read_pickup_schedule(client, api_base)
            pickup_blocked = _apply_pickup_schedule(item.detail, work, pickup)
        technical_blocked = execution_blocked or pickup_blocked
        item.detail = {**item.detail, "technical_work": work,
                       "technical_blocked": technical_blocked,
                       "handoff_needed": observed_status == "completed_pending_revalidation" or terminal_failure or technical_blocked}
        if terminal_failure:
            item.detail = {**item.detail, "technical_blocked": True}
        action = (
            "technical_work_blocked" if terminal_failure or technical_blocked
            else "technical_work_completed" if observed_status == "completed_pending_revalidation"
            else "technical_work_dispatched"
        )
        evidence = {"task_id": task_id, "status": observed_status, "receipt": work["receipt"]}
        if execution_blocked and permission is not None:
            evidence["execution_permission"] = permission
        if pickup_blocked and pickup is not None:
            evidence["pickup_schedule"] = pickup
        await _save_event(db, item, action, evidence)
        return {"status": observed_status, "task_id": task_id, "created": True, "receipt": work["receipt"],
                "technical_blocked": technical_blocked}
    except Exception as exc:
        work.update({"status": "dispatch_pending", "task_owned": True, "error": type(exc).__name__, "observed_at": _now()})
        item.detail = {**item.detail, "technical_work": work, "technical_blocked": False}
        await _save_event(db, item, "technical_work_dispatch_failed", {"error_type": type(exc).__name__})
        return {"status": "dispatch_pending", "task_id": None, "created": False, "error": type(exc).__name__}


async def reconcile_technical_work(db: AsyncSession) -> dict[str, Any]:
    """Replay lost acknowledgements and observe SummitFlow task lifecycle."""
    rows = list((await db.execute(select(ContextMaintenanceItem).where(
        ContextMaintenanceItem.state.in_((*ACTIVE_STATES, "resolved", "dismissed"))
    ))).scalars())
    counts = {"inspected": 0, "replayed": 0, "completed": 0, "blocked": 0, "errors": 0}
    api_base = await _project_api_url()
    gated_items = [
        item for item in rows
        if str((item.detail or {}).get("technical_work", {}).get("status") or "") in _EXECUTION_GATED_TASK_STATUSES
        and (item.detail or {}).get("technical_work", {}).get("task_id")
    ]
    permission = await _execution_permission(db) if gated_items else None
    pickup: dict[str, Any] | None = None
    if gated_items:
        if api_base:
            async with httpx.AsyncClient(timeout=30.0) as client:
                pickup = await _read_pickup_schedule(client, api_base)
        else:
            pickup = {"available": False, "reason": "summitflow_api_url_unavailable"}
    for item in rows:
        work = dict((item.detail or {}).get("technical_work") or {})
        if not work:
            continue
        if item.state not in ACTIVE_STATES and (item.resolution or {}).get("work_receipt"):
            continue
        task_id = work.get("task_id")
        status = str(work.get("status") or "")
        if not task_id and item.state not in ACTIVE_STATES and status in {"dispatch_pending", "dispatching"}:
            if not api_base:
                counts["errors"] += 1
                continue
            before_detail = dict(item.detail or {})
            raw_request = work.get("request")
            request: dict[str, Any] = raw_request if isinstance(raw_request, dict) else {}
            request_key = str(work.get("external_request_key") or request.get("external_request_key") or _external_request_key(item))
            endpoint = f"{api_base.rstrip('/')}/projects/{_TASK_PROJECT}/tasks"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(endpoint, json=request)
                if response.status_code < 400:
                    parsed = response.json()
                    body = parsed if isinstance(parsed, dict) else {}
                    task_id = body.get("id") or body.get("task_id")
                    if isinstance(task_id, str) and task_id:
                        receipt = _receipt(body)
                        work.update({"task_id": task_id, "receipt": receipt, "external_request_key": request_key,
                                     "external_payload_digest": receipt.get("external_payload_digest"),
                                     "observed_at": _now(), "task_owned": False, "generation": _generation(item)})
                        if str(body.get("status") or "") == "completed":
                            work["status"] = "completed_pending_revalidation"
                            item.resolution = {**(item.resolution or {}), "work_receipt": receipt}
                        item.detail = {**(item.detail or {}), "technical_work": work}
                        await _save_observation(db, item, before_detail, "technical_work_observed", {"task_id": task_id, "status": work.get("status"), "receipt": receipt})
            except Exception:
                counts["errors"] += 1
            continue
        if not task_id:
            if status in {"dispatch_pending", "dispatching"}:
                result = await dispatch_technical_work(db, item, reason="Replay the frozen idempotent request after an uncertain delivery.")
                counts["replayed"] += int(bool(result.get("created")))
            continue
        if status == "completed_pending_revalidation" or (status == "blocked" and not task_id):
            if item.state not in ACTIVE_STATES and isinstance(work.get("receipt"), dict):
                item.resolution = {**(item.resolution or {}), "work_receipt": work["receipt"]}
                await _save_event(db, item, "technical_work_receipt_retained", {"task_id": task_id, "receipt": work["receipt"]})
            continue
        if not api_base:
            if status in _EXECUTION_GATED_TASK_STATUSES and permission is not None and pickup is not None:
                before_detail = dict(item.detail or {})
                execution_blocked = _apply_execution_permission(item.detail, work, permission)
                pickup_blocked = _apply_pickup_schedule(item.detail, work, pickup)
                work.update({"task_owned": False, "technical_blocked": True, "observed_at": _now()})
                item.detail = {**item.detail, "technical_work": work, "technical_blocked": True, "handoff_needed": True}
                await _save_observation(
                    db,
                    item,
                    before_detail,
                    "technical_work_blocked",
                    {"task_id": task_id, "reason": pickup.get("reason"),
                     "execution_permission": permission if execution_blocked else None,
                     "pickup_schedule": pickup if pickup_blocked else None},
                )
                counts["blocked"] += 1
                continue
            counts["errors"] += 1
            continue
        endpoint = f"{api_base.rstrip('/')}/projects/{_TASK_PROJECT}/tasks/{task_id}"
        counts["inspected"] += 1
        before_detail = dict(item.detail or {})
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(endpoint)
            if response.status_code == 404:
                observed_status = "archived"
                body: dict[str, Any] = {"id": task_id, "status": observed_status, "archived": True}
            else:
                response.raise_for_status()
                parsed = response.json()
                body = parsed if isinstance(parsed, dict) else {}
                observed_status = "archived" if body.get("archived") else str(body.get("status") or "unknown")
            if observed_status == "completed":
                receipt = _receipt(body)
                if status == "blocked" and _same_completed_receipt(work.get("receipt"), receipt):
                    if item.state not in ACTIVE_STATES:
                        item.resolution = {**(item.resolution or {}), "work_receipt": receipt}
                        await _save_event(db, item, "technical_work_receipt_retained", {"task_id": task_id, "receipt": receipt})
                    continue
                _clear_queued_gate_markers(work)
                generation = _generation(item)
                work.update({"status": "completed_pending_revalidation", "task_owned": False, "receipt": receipt, "observed_at": _now(), "generation": generation})
                if item.state in {"resolved", "dismissed"}:
                    item.resolution = {**(item.resolution or {}), "work_receipt": receipt}
                item.detail = {**item.detail, "technical_work": work, "handoff_needed": True, "technical_blocked": False}
                await _save_observation(db, item, before_detail, "technical_work_completed", {"task_id": task_id, "next": "pending_revalidation"})
                counts["completed"] += 1
            elif observed_status in _TERMINAL_TASK_STATUSES or observed_status == "archived":
                _clear_queued_gate_markers(work)
                work.update({"status": observed_status, "task_owned": False, "technical_blocked": True, "receipt": _receipt(body), "observed_at": _now(), "generation": _generation(item)})
                item.detail = {**item.detail, "technical_work": work, "technical_blocked": True, "handoff_needed": True}
                await _save_observation(db, item, before_detail, "technical_work_blocked", {"task_id": task_id, "status": observed_status})
                counts["blocked"] += 1
            else:
                work.update({"status": observed_status, "task_owned": True, "receipt": _receipt(body), "observed_at": _now(), "generation": _generation(item)})
                execution_blocked = False
                pickup_blocked = False
                if observed_status in _EXECUTION_GATED_TASK_STATUSES:
                    if permission is None or pickup is None:
                        pickup = {"available": False, "reason": "summitflow_pickup_status_unavailable"}
                    execution_blocked = _apply_execution_permission(item.detail, work, permission or {
                        "allowed": False,
                        "permission_tier": "unknown",
                        "auto_exec_enabled": False,
                        "in_time_window": False,
                        "reason": "execution_permission_unavailable",
                    })
                    pickup_blocked = _apply_pickup_schedule(item.detail, work, pickup)
                else:
                    _clear_queued_gate_markers(work)
                technical_blocked = execution_blocked or pickup_blocked
                item.detail = {**item.detail, "technical_work": work,
                               "technical_blocked": technical_blocked,
                               "handoff_needed": technical_blocked}
                action = "technical_work_blocked" if technical_blocked else "technical_work_observed"
                evidence = {"task_id": task_id, "status": observed_status}
                if execution_blocked and permission is not None:
                    evidence["execution_permission"] = permission
                if pickup_blocked:
                    evidence["pickup_schedule"] = pickup
                await _save_observation(db, item, before_detail, action, evidence)
                if technical_blocked:
                    counts["blocked"] += 1
        except Exception as exc:
            work.update({"error": type(exc).__name__, "observed_at": _now()})
            if status in _EXECUTION_GATED_TASK_STATUSES and permission is not None and pickup is not None and not pickup.get("available"):
                _apply_execution_permission(item.detail, work, permission)
                _apply_pickup_schedule(item.detail, work, pickup)
                work.update({"task_owned": False, "technical_blocked": True})
                item.detail = {**item.detail, "technical_work": work, "technical_blocked": True, "handoff_needed": True}
                await _save_observation(db, item, before_detail, "technical_work_blocked", {
                    "task_id": task_id,
                    "reason": pickup.get("reason"),
                })
                counts["blocked"] += 1
            else:
                item.detail = {**item.detail, "technical_work": work}
                await _save_observation(db, item, before_detail, "technical_work_observation_failed", {"task_id": task_id, "error_type": type(exc).__name__})
                counts["errors"] += 1
    return counts


__all__ = ["dispatch_technical_work", "reconcile_technical_work"]
