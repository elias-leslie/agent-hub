"""Fail-closed verification of completed canonical maintenance work."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.context_governance import ContextMaintenanceItem, ContextRecord
from app.services.context_governance import get_source
from app.services.context_maintenance import evidence_identity
from app.services.context_policy import semantic_hash, source_revision
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    build_canonical_context_delivery,
)


class WorkProductVerification(TypedDict):
    verified: bool
    reason: str
    item_id: str | None
    item_version: int | None
    task_id: str | None
    external_request_key: str | None
    external_payload_digest: str | None
    state: str | None
    change_id: str | None
    event_id: str | None
    verified_sources: list[dict[str, str]]
    payload_hash: str | None
    verification: str


def _result(
    *,
    verified: bool,
    reason: str,
    row: ContextMaintenanceItem,
    task_id: str | None = None,
    external_request_key: str | None = None,
    external_payload_digest: str | None = None,
    change_id: str | None = None,
    event_id: str | None = None,
    verified_sources: list[dict[str, str]] | None = None,
    payload_hash: str | None = None,
) -> WorkProductVerification:
    return {
        "verified": verified,
        "reason": reason,
        "item_id": getattr(row, "id", None),
        "item_version": getattr(row, "version", None),
        "task_id": task_id,
        "external_request_key": external_request_key,
        "external_payload_digest": external_payload_digest,
        "state": getattr(row, "state", None),
        "change_id": change_id,
        "event_id": event_id,
        "verified_sources": verified_sources or [],
        "payload_hash": payload_hash,
        "verification": "canonical_generation",
    }


def _receipt_matches(
    receipt: Any,
    *,
    task_id: str,
    external_request_key: str,
    external_payload_digest: str,
) -> bool:
    if not isinstance(receipt, dict):
        return False
    return (
        receipt.get("id") == task_id
        and receipt.get("project_id") == "agent-hub"
        and receipt.get("external_origin") == "agent-hub-context-maintenance"
        and receipt.get("external_request_key") == external_request_key
        and receipt.get("external_payload_digest") == external_payload_digest
    )


async def _live_sources(
    db: AsyncSession,
    row: ContextMaintenanceItem,
) -> tuple[list[dict[str, str]] | None, str | None]:
    sources = row.sources if isinstance(row.sources, list) else []
    live: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict) or source.get("source_type") not in {"prompt", "memory"}:
            return None, "maintenance evidence contains an unknown source"
        source_type = str(source["source_type"])
        source_id = str(source.get("source_id") or "")
        if not source_id:
            return None, "maintenance evidence is incomplete"
        try:
            current = await get_source(db, source_type, source_id)
        except HTTPException:
            return None, "maintenance source is missing"
        except Exception:
            return None, "maintenance source verification unavailable"
        current_revision = source_revision(current)
        live.append({"source_type": source_type, "source_id": source_id, "revision": current_revision})
    return sorted(live, key=lambda item: (item["source_type"], item["source_id"])), None


async def verify_work_product(
    db: AsyncSession,
    row: ContextMaintenanceItem,
    *,
    task_id: str | None,
    external_request_key: str | None,
    external_payload_digest: str | None,
    generation: int | None,
) -> WorkProductVerification:
    """Verify one exact external work receipt against current canonical context."""
    work = (row.detail or {}).get("technical_work")
    work = work if isinstance(work, dict) else {}
    receipt = work.get("receipt")
    bound_task_id = work.get("task_id")
    bound_request_key = work.get("external_request_key") or (work.get("request") or {}).get("external_request_key")
    bound_digest = work.get("external_payload_digest") or (receipt or {}).get("external_payload_digest")
    bound_generation = work.get("generation", (row.detail or {}).get("generation"))
    if row.state not in {"resolved", "dismissed"}:
        return _result(verified=False, reason="maintenance item is not closed", row=row)
    if not all(isinstance(value, str) and value for value in (task_id, external_request_key, external_payload_digest)):
        return _result(verified=False, reason="work identity is incomplete", row=row)
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        return _result(verified=False, reason="work generation is incomplete", row=row)
    if (
        bound_task_id != task_id
        or bound_request_key != external_request_key
        or bound_digest != external_payload_digest
        or bound_generation != generation
        or not _receipt_matches(
            receipt,
            task_id=task_id,
            external_request_key=external_request_key,
            external_payload_digest=external_payload_digest,
        )
    ):
        return _result(
            verified=False,
            reason="work receipt does not match the bound maintenance task",
            row=row,
            task_id=task_id,
            external_request_key=external_request_key,
            external_payload_digest=external_payload_digest,
        )
    resolution = row.resolution if isinstance(row.resolution, dict) else {}
    required_policy = resolution.get("required_policy")
    if resolution.get("verification") != "canonical_generation" or not isinstance(required_policy, dict) or required_policy.get("state") != "complete":
        return _result(verified=False, reason="resolution does not retain a complete canonical generation", row=row)
    verified_sources = resolution.get("verified_sources")
    if not isinstance(verified_sources, list) or not verified_sources:
        return _result(verified=False, reason="resolution has no verified source evidence", row=row)
    if not isinstance(row.sources, list) or not row.sources:
        return _result(verified=False, reason="maintenance evidence has no sources", row=row)
    live_sources, source_error = await _live_sources(db, row)
    if source_error or live_sources is None:
        return _result(verified=False, reason=source_error or "live source verification unavailable", row=row)
    expected_sources = evidence_identity(row.sources or [])
    if not expected_sources or len(expected_sources) != len(row.sources):
        return _result(verified=False, reason="maintenance evidence has no canonical sources", row=row)
    expected_source_keys = {(item["source_type"], item["source_id"]) for item in expected_sources}
    supplied_sources = sorted(
        (
            {"source_type": str(item.get("source_type")), "source_id": str(item.get("source_id")), "revision": str(item.get("revision"))}
            for item in verified_sources
            if isinstance(item, dict)
        ),
        key=lambda item: (item["source_type"], item["source_id"]),
    )
    if (
        {(item["source_type"], item["source_id"]) for item in supplied_sources} != expected_source_keys
        or supplied_sources != live_sources
    ):
        return _result(verified=False, reason="resolution source evidence is stale or incomplete", row=row)

    change_id = resolution.get("change_id")
    change = None
    changes: list[dict[str, Any]] = []
    if change_id:
        change = await db.get(ContextRecord, change_id)
        raw_changes = change.payload.get("changes") if change and isinstance(change.payload, dict) else None
        if not change or change.kind != "change" or not isinstance(raw_changes, list) or not raw_changes or not all(isinstance(item, dict) for item in raw_changes):
            return _result(verified=False, reason="canonical change receipt is missing", row=row, verified_sources=live_sources)
        changes = cast(list[dict[str, Any]], raw_changes)
        changed_keys: set[tuple[str, str]] = set()
        for item in changes:
            before = item.get("before") if isinstance(item, dict) else None
            if not isinstance(before, dict):
                return _result(verified=False, reason="canonical change receipt is malformed", row=row, verified_sources=live_sources)
            key = (str(before.get("source_type") or ""), str(before.get("source_id") or ""))
            after_revision = item.get("after_revision")
            if key not in expected_source_keys:
                return _result(verified=False, reason="canonical change receipt does not match evidence", row=row, verified_sources=live_sources)
            original = next((source for source in row.sources if (source.get("source_type"), source.get("source_id")) == key), None)
            current = next((source for source in live_sources if (source["source_type"], source["source_id"]) == key), None)
            if not original or not current or original.get("revision") != "sha256:" + semantic_hash(before) or after_revision != current["revision"]:
                return _result(verified=False, reason="canonical change receipt is stale", row=row, verified_sources=live_sources)
            changed_keys.add(key)
        for source in row.sources:
            key = (source.get("source_type"), source.get("source_id"))
            if key not in changed_keys:
                current = next((item for item in live_sources if (item["source_type"], item["source_id"]) == key), None)
                if not current or current["revision"] != source.get("revision"):
                    return _result(verified=False, reason="unrecorded evidence changed after the work receipt", row=row, verified_sources=live_sources)
    elif any(source.get("revision") != next((item["revision"] for item in live_sources if item["source_type"] == source.get("source_type") and item["source_id"] == source.get("source_id")), None) for source in row.sources):
        return _result(verified=False, reason="resolution has no change receipt for changed evidence", row=row, verified_sources=live_sources)

    recorded_context = None
    if change and isinstance(change.payload, dict):
        recorded_context = change.payload.get("context")
    if not isinstance(recorded_context, dict):
        recorded_context = {"consumer_surface": "agent_runtime", **(row.context or {})}
    try:
        delivery_context = CanonicalContextDeliveryRequest.model_validate(recorded_context)
    except Exception:
        return _result(verified=False, reason="canonical context binding is unavailable", row=row, verified_sources=live_sources)
    try:
        delivery = await build_canonical_context_delivery(db, delivery_context)
    except Exception:
        return _result(verified=False, reason="canonical delivery verification unavailable", row=row, verified_sources=live_sources)
    if delivery.status != "ok" or delivery.required_policy.state != "complete":
        return _result(verified=False, reason="canonical generation is incomplete", row=row, verified_sources=live_sources, payload_hash=getattr(delivery, "payload_hash", None))

    events = (await db.execute(select(ContextRecord).where(
        ContextRecord.kind == "maintenance",
        ContextRecord.payload["item_id"].as_string() == row.id,
    ).order_by(ContextRecord.created_at))).scalars()
    event_match = None
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        raw_evidence = payload.get("evidence")
        evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
        event_sources = payload.get("sources")
        raw_resolution = evidence.get("resolution")
        event_resolution = raw_resolution if isinstance(raw_resolution, dict) else {}
        event_source_records = sorted(
            (
                {
                    "source_type": str(item.get("source_type")),
                    "source_id": str(item.get("source_id")),
                    "revision": str(item.get("revision")),
                }
                for item in event_sources
                if isinstance(item, dict)
            ),
            key=lambda item: (item["source_type"], item["source_id"]),
        ) if isinstance(event_sources, list) else []
        if (
            payload.get("action") in ({"apply", "resolve", "repair"} if row.state == "resolved" else {"dismiss"})
            and
            payload.get("state") in {"resolved", "dismissed"}
            and payload.get("state") == row.state
            and payload.get("version") == row.version
            and isinstance(event_sources, list)
            and len(event_source_records) == len(event_sources)
            and event_source_records == expected_sources
            and (not change_id or event_resolution.get("change_id") == change_id)
            and event_resolution == resolution
        ):
            event_match = event
            break
    if event_match is None:
        return _result(verified=False, reason="immutable maintenance work receipt is missing", row=row, verified_sources=live_sources, payload_hash=delivery.payload_hash)

    return _result(
        verified=True,
        reason="canonical maintenance work and delivery verified",
        row=row,
        task_id=task_id,
        external_request_key=external_request_key,
        external_payload_digest=external_payload_digest,
        change_id=change_id,
        event_id=event_match.id,
        verified_sources=live_sources,
        payload_hash=delivery.payload_hash,
    )


__all__ = ["WorkProductVerification", "verify_work_product"]
