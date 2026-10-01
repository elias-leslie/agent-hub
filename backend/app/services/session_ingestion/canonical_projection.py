"""Agent Hub's dormant canonical writer and server-owned promotion gate.

Live positions are explicitly provisional until exact rollout identities supply the
legacy positions. Receipt, identity, relocation and cursor changes share one lock.
"""

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NativeCommandEntity,
    NativeObservationSource,
    NativeProjectionState,
    Session,
    SessionEvent,
)
from app.services.event_storage import lock_session_event_ingestion, store_event

from .app_server_observations import SUPPORTED_VERSIONS, protocol_contract
from .native_models import NativeObservation
from .service import SessionIngestionConflict

ACCEPTANCE_CHECKS = ("identity_aliases", "canonical_ordering", "lifecycle_usage", "protocol_conformance", "storage_recovery")
RESERVED_SEQUENCE = 1_000_000_000


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def projection_status(db: AsyncSession, session: Session) -> dict[str, Any]:
    state = await db.get(NativeProjectionState, session.id)
    evidence = state.acceptance if state and isinstance(state.acceptance, dict) else {}
    checks = evidence.get("checks", {})
    blockers = [key + "_unproven" for key in ACCEPTANCE_CHECKS if not isinstance(checks, dict) or checks.get(key) is not True]
    digest = evidence.get("evidence_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        blockers.append("server_acceptance_evidence_unavailable")
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    managed = [source for source in sources if source.registration.get("source_kind") == "app_server" and source.registration.get("collector_id") == "summitflow/codex-managed" and source.registration.get("_protocol_profile_version", source.registration.get("provider_version")) in SUPPORTED_VERSIONS and source.registration.get("schema_fingerprint") == protocol_contract(source.registration.get("_protocol_profile_version", source.registration["provider_version"]))[0]]
    if not managed:
        blockers.append("managed_source_unqualified")
    if not any(source.registration.get("source_kind") == "rollout" and source.authenticity == "local_verified" for source in sources):
        blockers.append("verified_rollout_recovery_unavailable")
    return {"promotion_requested": bool(state and state.mode == "canonical_managed"), "promotion_eligible": not blockers, "promotion_blockers": blockers, "promotion_state": state.mode if state else "shadow", "projection_authority": "canonical_managed" if state and state.mode == "canonical_managed" and not blockers else "rollout"}


async def record_projection_acceptance(db: AsyncSession, session: Session, evidence: dict[str, Any]) -> None:
    """Server-side acceptance runner only; intentionally no collector-facing API."""
    await lock_session_event_ingestion(db, session.id)
    state = await db.get(NativeProjectionState, session.id)
    if state is None:
        state = NativeProjectionState(session_id=session.id, mode="shadow", next_sequence=RESERVED_SEQUENCE)
        db.add(state)
    state.acceptance = evidence
    await db.commit()


async def set_projection_mode(db: AsyncSession, session: Session, mode: str) -> dict[str, Any]:
    await lock_session_event_ingestion(db, session.id)
    if mode not in {"shadow", "canonical_managed"}:
        raise SessionIngestionConflict("native_projection_mode_invalid", "Unknown native projection mode.")
    state = await db.get(NativeProjectionState, session.id)
    if mode == "canonical_managed":
        status = await projection_status(db, session)
        if not status["promotion_eligible"]:
            raise SessionIngestionConflict("native_projection_acceptance_required", "Server-owned acceptance evidence and managed rollout recovery are required.")
        from ._native_provenance import validate_native_provenance
        metadata = session.provider_metadata or {}
        await asyncio.to_thread(validate_native_provenance, session.id, session.project_id, session.parent_session_id, metadata, transcript_path=metadata.get("transcript_path"))
    if state is None:
        state = NativeProjectionState(session_id=session.id, mode=mode, next_sequence=RESERVED_SEQUENCE)
        db.add(state)
    state.mode = mode
    await db.commit()
    return await projection_status(db, session)


async def _reserve(db: AsyncSession, session: Session, state: NativeProjectionState) -> int:
    sequence = max(state.next_sequence, RESERVED_SEQUENCE)
    while (await db.execute(select(SessionEvent.id).where(SessionEvent.session_id == session.id, SessionEvent.turn == 1, SessionEvent.sequence == sequence))).scalar_one_or_none() is not None:
        sequence += 1
    if sequence >= 2_147_483_646:
        raise SessionIngestionConflict("native_projection_positions_exhausted", "Provisional projection positions are exhausted.")
    state.next_sequence = sequence + 1
    return sequence


def _output(observation: NativeObservation, entity: NativeCommandEntity) -> dict[str, Any]:
    item = observation.payload.get("item", {})
    output = {"status": entity.status, "is_error": entity.status in {"failed", "declined"}}
    for key in ("stdout", "stderr"):
        if isinstance(item.get(key), str):
            output[key] = item[key]
    if isinstance(item.get("aggregatedOutput"), str):
        output["output"] = item["aggregatedOutput"]
    if "exit_code" in entity.command:
        output["exit_code"] = entity.command["exit_code"]
    return output


async def project_live_observation(db: AsyncSession, session: Session, source: NativeObservationSource, observation: NativeObservation, entity: NativeCommandEntity | None) -> list[str]:
    state = await db.get(NativeProjectionState, session.id)
    if state is None or state.mode != "canonical_managed" or observation.origin != "live" or source.registration.get("collector_id") != "summitflow/codex-managed":
        return []
    # The mode is server-owned and source qualification is rechecked on each receipt.
    if not (await projection_status(db, session))["promotion_eligible"]:
        return []
    if entity is not None:
        rows = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session.id, SessionEvent.id.in_(entity.projection_event_ids)))).scalars().all() if entity.projection_event_ids else []
        terminal = entity.status in {"completed", "failed", "declined"}
        incoming_terminal = observation.payload.get("item", {}).get("status") in {"completed", "failed", "declined", "success", "succeeded"}
        result = next((row for row in rows if row.event_type == "tool_result"), None)
        if result is not None and terminal and incoming_terminal and str(result.source_event_id).startswith("native-command:"):
            result.tool_output = _output(observation, entity)
        required = ("tool_use", "tool_result") if terminal else ("tool_use",)
        ids = list(entity.projection_event_ids)
        for event_type in required:
            if any(row.event_type == event_type for row in rows):
                continue
            sequence = await _reserve(db, session, state)
            marker = {"native_turn_id": entity.turn_id, "ordering": "provisional"}
            tool_input = {"command": entity.command["command"], **({"cwd": entity.command["cwd"]} if "cwd" in entity.command else {}), **marker} if event_type == "tool_use" else marker
            event = await store_event(db, session.id, event_type, turn=1, sequence=sequence, tool_name="Bash" if event_type == "tool_use" else None, call_id=entity.item_id, tool_input=tool_input, tool_output=_output(observation, entity) if event_type == "tool_result" else None, source_event_id=f"native-command:{entity.id}:{event_type}", session=session)
            await db.flush()
            ids.append(str(event.id))
        entity.projection_event_ids = ids
        return ids
    if observation.kind not in {"lifecycle", "approval_request", "approval_response", "approval_resolution"}:
        return []
    method = observation.source_reference.get("wire_method")
    if observation.kind == "lifecycle" and method not in {"turn/started", "turn/completed", "thread/status/changed"}:
        return []
    key = _digest([source.registration["namespace"], observation.thread_id, observation.turn_id, observation.item_id, observation.kind, method, observation.payload.get("status"), observation.payload.get("turn", {}).get("status"), observation.source_reference.get("request_id", observation.payload.get("request_id", observation.payload.get("requestId"))), observation.source_reference.get("approval_request_position"), observation.source_reference.get("connection_id")])
    event_source = "native-audit:" + key
    existing = (await db.execute(select(SessionEvent.id).where(SessionEvent.session_id == session.id, SessionEvent.source_event_id == event_source))).scalar_one_or_none()
    if existing:
        return [str(existing)]
    event = await store_event(db, session.id, "native_lifecycle" if observation.kind == "lifecycle" else "native_approval", turn=1, sequence=await _reserve(db, session, state), tool_input={"native_turn_id": observation.turn_id, "kind": observation.kind, "method": method, "ordering": "provisional", "approval_decision": "unknown"} if observation.kind != "lifecycle" else {"native_turn_id": observation.turn_id, "kind": observation.kind, "method": method, "ordering": "provisional"}, source_event_id=event_source, session=session)
    await db.flush()
    return [str(event.id)]


async def align_rollout_projection(db: AsyncSession, session: Session, entity: NativeCommandEntity, pair: list[Any]) -> None:
    """Relocate the same live pair before rollout append; never allocate duplicates."""
    if len(pair) != 2 or not entity.projection_event_ids:
        return
    rows = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session.id, SessionEvent.id.in_(entity.projection_event_ids)))).scalars().all()
    if not rows or not all(str(row.source_event_id).startswith("native-command:") for row in rows):
        return
    projected_types = {row.event_type for row in rows}
    targets = {(event.turn, event.sequence) for event in pair if event.event_type in projected_types}
    occupied = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session.id, SessionEvent.turn.in_([event.turn for event in pair])))).scalars().all()
    if any((event.turn, event.sequence) in targets and str(event.id) not in entity.projection_event_ids for event in occupied):
        raise SessionIngestionConflict("native_projection_position_conflict", "An unrelated event owns the exact rollout projection position.")
    for native in pair:
        if native.event_type not in projected_types:
            continue
        row = next(event for event in rows if event.event_type == native.event_type)
        row.turn, row.sequence = native.turn, native.sequence
        row.source_event_id, row.source_timestamp = native.source_event_id, native.source_timestamp
        row.tool_input, row.tool_output, row.duration_ms = native.tool_input, native.tool_output, native.duration_ms
    await db.flush()
