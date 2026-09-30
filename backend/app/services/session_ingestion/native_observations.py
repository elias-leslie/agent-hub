"""Canonical native receipts and shadow reconciliation under the session ingest lock."""

import asyncio
import hashlib
import json
import shlex
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    NativeObservationSource,
    Session,
)
from app.services.event_storage import lock_session_event_ingestion

from .adapters._event_builders import _native_shell_command
from .app_server_observations import interpret_wire
from .native_models import (
    NativeObservation,
    NativeObservationBatch,
    NativeObservationDisposition,
    NativeObservationResult,
    NativeSourceReceipt,
    NativeSourceRegistration,
)
from .service import SessionIngestionConflict


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


async def register_native_source(
    db: AsyncSession, session: Session, request: NativeSourceRegistration,
) -> NativeSourceReceipt:
    """Called only by the authenticated internal execution owner API."""
    await lock_session_event_ingestion(db, session.id)
    await db.refresh(session)
    if session.provider != "codex" or request.thread_id != session.id:
        raise SessionIngestionConflict("native_source_identity_mismatch", "The source must name the registered native thread.")
    metadata = dict(session.provider_metadata or {})
    previous_namespace = metadata.get("native_observation_namespace")
    if previous_namespace is not None and previous_namespace != request.namespace:
        raise SessionIngestionConflict("native_namespace_immutable", "The verified native namespace cannot change.")
    authenticity = "collector_attested"
    if request.source_kind == "rollout":
        from ._native_provenance import validate_native_provenance

        if not request.transcript_path or request.transcript_path != metadata.get("transcript_path"):
            raise SessionIngestionConflict("native_source_path_mismatch", "Rollout registration requires the exact registered local path.")
        validate_native_provenance(session.id, session.project_id, session.parent_session_id, metadata, transcript_path=request.transcript_path)
        authenticity = "local_verified"
    elif request.transcript_path is not None or request.reconcile_existing_rollout:
        raise SessionIngestionConflict("native_source_path_invalid", "App Server sources cannot claim local reread provenance.")
    registration = request.model_dump(mode="json")
    # Include the execution binding so epochs cannot alias across child sessions.
    source_id = _digest([session.id, request.namespace, request.source_kind, request.producer_id, request.epoch])
    source = await db.get(NativeObservationSource, source_id)
    new_source = source is None
    if source is not None and NativeSourceRegistration.model_validate({key: value for key, value in source.registration.items() if not key.startswith("_")}).model_dump(mode="json") != registration:
        raise SessionIngestionConflict("native_source_registration_conflict", "An existing producer epoch has different registration evidence.")
    if source is None:
        if request.source_kind == "rollout":
            from .adapters.transcript_parsers import _load_parse_checkpoint

            other_sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
            if any(row.registration["source_kind"] == "rollout" for row in other_sources):
                raise SessionIngestionConflict("native_rollout_source_already_registered", "This slice supports one local rollout ledger per native session.")
            retained = metadata.get("transcript_ingestion") or {}
            registration["_command_position_base"] = 0 if request.reconcile_existing_rollout else _load_parse_checkpoint(retained.get("checkpoint")).codex_model_state.get("command_position", 0)
        source = NativeObservationSource(id=source_id, session_id=session.id, registration=registration, authenticity=authenticity, committed_position=0)
        db.add(source)
        await db.flush()
    if new_source and request.source_kind == "rollout" and request.reconcile_existing_rollout:
        # Re-read native history for receipt reconciliation only. Keep the rollout
        # parser's existing byte checkpoint and timeline projection unchanged.
        from .adapters.transcript_parsers import read_incremental_transcript_events

        events, _ = await asyncio.to_thread(read_incremental_transcript_events, request.transcript_path, None)
        await _retain_rollout_source_commands(db, session, source, events)
    metadata["native_observation_namespace"] = request.namespace
    session.provider_metadata = metadata
    await db.commit()
    return NativeSourceReceipt(source_id=source_id, committed_position=source.committed_position, authenticity=source.authenticity)


def _command(observation: NativeObservation) -> tuple[str, dict[str, Any]] | None:
    """Interpret only the tested command slice; preserve the original in its receipt."""
    item = observation.payload.get("item")
    if not isinstance(item, dict):
        return None
    expected = "CommandExecution" if observation.origin == "rollout_record" else "commandExecution"
    if item.get("type") != expected or item.get("id") != observation.item_id:
        return None
    status = item.get("status")
    status = {"inProgress": "running", "in_progress": "running", "success": "completed", "succeeded": "completed"}.get(status, status)
    if status not in {"running", "completed", "failed", "declined"}:
        return None
    command = item.get("command")
    if not isinstance(command, str) and not (isinstance(command, list) and all(isinstance(part, str) for part in command)):
        return None
    canonical: dict[str, Any] = {"command": _native_shell_command(command) or command}
    if isinstance(command, str):
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = []
        # Pinned runtime renders its native argv as shell-escaped display text.
        # Unwrap only an attributable native shell invocation; arbitrary command
        # text or content similarity cannot establish identity.
        if len(argv) == 3 and PurePosixPath(argv[0]).name in {"bash", "sh", "dash", "zsh"}:
            canonical["command"] = _native_shell_command(argv) or command
    for source_key, key in (("cwd", "cwd"), ("exitCode", "exit_code"), ("exit_code", "exit_code")):
        if item.get(source_key) is not None:
            canonical[key] = item[source_key]
    cwd = canonical.get("cwd")
    if isinstance(cwd, str) and cwd.startswith("file:"):
        parsed_cwd = urlsplit(cwd)
        if parsed_cwd.netloc in {"", "localhost"} and not parsed_cwd.query and not parsed_cwd.fragment:
            canonical["cwd"] = unquote(parsed_cwd.path)
    # Combined API output and individual rollout streams have different fidelity.
    # Retain both as evidence instead of using rendered text for identity or equality.
    return status, canonical


async def _issue(db: AsyncSession, source_id: str, observation: NativeObservation, code: str) -> None:
    payload = observation.model_dump(mode="json")
    key = _digest([source_id, observation.position, code, payload])
    if await db.get(NativeObservationIssue, key) is None:
        db.add(NativeObservationIssue(id=key, source_id=source_id, position=observation.position, code=code, observation=payload))
        await db.flush()


async def approval_subject(db: AsyncSession, source_id: str, observation: NativeObservation) -> dict[str, Any] | None:
    """Resolve only exact request IDs within this source/connection and thread."""
    wire = observation.payload
    request_id = wire.get("request_id") if observation.kind == "approval_response" else wire.get("params", {}).get("requestId") if wire.get("method") == "serverRequest/resolved" else None
    if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
        return None
    query = select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == source_id, NativeObservationReceipt.position < observation.position, cast(NativeObservationReceipt.observation["payload"]["id"], String) == json.dumps(request_id))
    connection_id = observation.source_reference.get("connection_id")
    if connection_id is not None:
        query = query.where(NativeObservationReceipt.observation["source_reference"]["connection_id"].as_string() == connection_id)
    prior = (await db.execute(query.order_by(NativeObservationReceipt.position.desc()).limit(1))).scalar_one_or_none()
    if prior is None or prior.disposition != "retained" or prior.issue_code is not None or not prior.observation["payload"].get("method", "").endswith("/requestApproval"):
        return None
    params = prior.observation["payload"]["params"]
    return {"source_id": source_id, "request_position": prior.position, "request_id": request_id, "thread_id": params["threadId"], "turn_id": params["turnId"], "item_id": params["itemId"], "connection_id": connection_id}


async def _retain(
    db: AsyncSession, source: NativeObservationSource, observation: NativeObservation,
    projection_event_ids: list[str] | None = None,
) -> NativeObservationDisposition:
    if observation.thread_id != source.session_id:
        # Binding failures never enter the trusted ledger or move the checkpoint.
        raise SessionIngestionConflict("native_observation_identity_mismatch", "The observation names another native thread.")
    if observation.origin == "rollout_record" and source.registration["source_kind"] != "rollout":
        raise SessionIngestionConflict("native_observation_origin_mismatch", "Only the local rollout adapter may submit rollout evidence.")
    if observation.origin != "rollout_record" and source.registration["source_kind"] != "app_server":
        raise SessionIngestionConflict("native_observation_origin_mismatch", "The observation does not match its registered source kind.")
    payload = observation.model_dump(mode="json")
    payload_hash = _digest(payload)
    existing = await db.get(NativeObservationReceipt, (source.id, observation.position))
    if existing is not None:
        if existing.payload_hash != payload_hash:
            await _issue(db, source.id, observation, "receipt_payload_conflict")
            return NativeObservationDisposition(position=observation.position, disposition="conflict", issue_code="receipt_payload_conflict")
        if projection_event_ids and existing.entity_id and existing.disposition in {"accounted", "reconciled"}:
            entity = await db.get(NativeCommandEntity, existing.entity_id)
            if entity is not None and not entity.projection_event_ids:
                entity.projection_event_ids = projection_event_ids
        return NativeObservationDisposition(position=observation.position, disposition="replayed", entity_id=existing.entity_id, issue_code=existing.issue_code)
    original_observation = observation
    observation, wire_issue = await asyncio.to_thread(interpret_wire, observation, source.registration)
    if observation.kind in {"approval_response", "approval_resolution"}:
        subject = await approval_subject(db, source.id, original_observation)
        if subject is None:
            wire_issue = "approval_request_unavailable"
        elif subject["thread_id"] != observation.thread_id or (observation.kind == "approval_response" and (observation.source_reference.get("turn_id") != subject["turn_id"] or observation.source_reference.get("item_id") != subject["item_id"])):
            wire_issue = "approval_subject_mismatch"
    disposition, code, entity_id = "unresolved", None, None
    if observation.history_owner_thread_id not in (None, observation.thread_id):
        disposition, code = "inherited", "inherited_history"
    elif wire_issue:
        disposition, code = "unsupported", wire_issue
    elif observation.kind == "capture_health":
        if observation.payload.get("state") in {"connected", "capture_gap", "disabled", "unsupported", "outbox_full", "disconnected"}:
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unsupported_capture_health"
    elif observation.kind == "approval_response" and wire_issue is None:
        disposition = "retained"
    elif observation.kind == "app_server_configuration":
        configuration = observation.payload
        if configuration.get("direction") in {"request", "response"} and configuration.get("method") in {"thread/start", "thread/fork", "thread/resume", "turn/start", "thread/settings/update"} and isinstance(configuration.get("params"), dict) and all(key in {"model", "effort", "reasoningEffort"} and (value is None or isinstance(value, str)) for key, value in configuration["params"].items()):
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unsupported_configuration_shape"
    elif observation.kind == "app_server_snapshot":
        # Recovery snapshots never establish live completeness or child work.
        disposition, code = "unresolved", "snapshot_identity_unverified"
    elif observation.kind in {"lifecycle", "approval_request", "approval_resolution", "usage_snapshot"}:
        # These are derived exclusively from validated wire evidence. They do not
        # append commands, token deltas, or grant any execution/approval authority.
        if payload["kind"] == "app_server_event":
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unverified_app_server_evidence"
    elif observation.kind != "command_execution":
        disposition, code = "unsupported", "unsupported_observation_kind"
    elif observation.identity_quality != "durable" or observation.origin == "active_resume_snapshot":
        code = "provisional_identity"
    elif not observation.turn_id or not observation.item_id:
        code = "missing_native_identity"
    elif (parsed := _command(observation)) is None:
        disposition, code = "unsupported", "unsupported_command_shape"
    else:
        status, command = parsed
        entity_id = _digest(["codex", source.registration["namespace"], observation.thread_id, observation.turn_id, observation.item_id])
        entity = await db.get(NativeCommandEntity, entity_id)
        if entity is None:
            entity = NativeCommandEntity(id=entity_id, session_id=source.session_id, namespace=source.registration["namespace"], thread_id=observation.thread_id, turn_id=observation.turn_id, item_id=observation.item_id, status=status, command=command, projection_event_ids=projection_event_ids or [], observed_model=None)
            db.add(entity)
            disposition = "accounted"
        elif any(entity.command[key] != value for key, value in command.items() if key in entity.command):
            disposition, code = "conflict", "entity_payload_conflict"
        elif entity.status in {"completed", "failed", "declined"} and status in {"completed", "failed", "declined"} and status != entity.status:
            disposition, code = "conflict", "entity_terminal_conflict"
        else:
            disposition = "reconciled"
            if entity.status == "running":
                entity.status = status
            entity.command = {**command, **entity.command}
            if projection_event_ids and not entity.projection_event_ids:
                entity.projection_event_ids = projection_event_ids
        await db.flush()
    receipt = NativeObservationReceipt(source_id=source.id, position=observation.position, payload_hash=payload_hash, observation=payload, disposition=disposition, issue_code=code, entity_id=entity_id)
    db.add(receipt)
    if code:
        await _issue(db, source.id, original_observation, code)
    await db.flush()
    return NativeObservationDisposition(position=observation.position, disposition=disposition, entity_id=entity_id, issue_code=code)


async def native_capture_status(db: AsyncSession, session: Session) -> dict[str, Any]:
    """Content-free, durable health. Queries never contact a native runtime."""
    from sqlalchemy import func

    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    health = []
    for source in sources:
        count, maximum = (await db.execute(select(func.count(), func.max(NativeObservationReceipt.position)).where(NativeObservationReceipt.source_id == source.id))).one()
        issues = (await db.execute(select(NativeObservationIssue.code, func.count()).where(NativeObservationIssue.source_id == source.id).group_by(NativeObservationIssue.code))).all()
        latest_health = (await db.execute(select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == source.id, NativeObservationReceipt.observation["kind"].as_string() == "capture_health").order_by(NativeObservationReceipt.position.desc()).limit(1))).scalar_one_or_none()
        # Health is project-visible; arbitrary retained payload fields belong only
        # in the internal raw-evidence queries, even for trusted collectors.
        public_health = None
        if latest_health:
            raw_health = latest_health.observation["payload"]
            public_health = {"state": raw_health["state"]} if latest_health.disposition == "retained" else {"state": "unsupported"}
            gaps = raw_health.get("capture_gaps")
            if isinstance(gaps, int) and not isinstance(gaps, bool) and gaps >= 0:
                public_health["capture_gaps"] = gaps
            if raw_health.get("transport") == "stdio":
                public_health["transport"] = "stdio"
        health.append({"source_id": source.id, "kind": source.registration["source_kind"], "provider_version": source.registration["provider_version"], "schema_fingerprint": source.registration["schema_fingerprint"], "authenticity": source.authenticity, "committed_position": source.committed_position, "receipt_count": count, "max_position": maximum or 0, "first_missing_position": source.committed_position + 1 if (maximum or 0) > source.committed_position else None, "issues": {code: n for code, n in issues}, "capture_health": public_health})
    return {"schema_version": "native-observation.v1", "session_id": session.id, "capture_mode": "app_server_registered" if any(row.registration["source_kind"] == "app_server" for row in sources) else "rollout_only", "projection_authority": "rollout", "promotion_state": "shadow", "observed_model": None, "sources": health}


async def _advance(db: AsyncSession, source: NativeObservationSource) -> None:
    while await db.get(NativeObservationReceipt, (source.id, source.committed_position + 1)) is not None:
        source.committed_position += 1


async def ingest_native_observations(
    db: AsyncSession, session: Session, source_id: str, request: NativeObservationBatch,
) -> NativeObservationResult:
    await lock_session_event_ingestion(db, session.id)
    source = await db.get(NativeObservationSource, source_id)
    if source is None or source.session_id != session.id:
        raise SessionIngestionConflict("native_source_unregistered", "Register this source with the execution owner first.")
    await db.refresh(source)
    if source.registration["source_kind"] != "app_server":
        raise SessionIngestionConflict("native_source_local_only", "Local rollout receipts are written only by transcript ingestion.")
    dispositions = [await _retain(db, source, observation) for observation in request.observations]
    await _advance(db, source)
    await db.commit()
    return NativeObservationResult(source_id=source.id, committed_position=source.committed_position, authenticity=source.authenticity, dispositions=dispositions)


async def retain_rollout_commands(db: AsyncSession, session: Session, events: list[Any]) -> None:
    """Add receipts and projection links inside the existing event/checkpoint transaction."""
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    source = next((row for row in sources if row.registration["source_kind"] == "rollout"), None)
    if source is None:
        return
    await _retain_rollout_source_commands(db, session, source, events)


async def _retain_rollout_source_commands(db: AsyncSession, session: Session, source: NativeObservationSource, events: list[Any]) -> None:
    from app.models import SessionEvent

    for index, event in enumerate(events):
        raw = event.native_observation
        if not raw:
            continue
        observation = NativeObservation.model_validate(raw)
        observation = observation.model_copy(update={"position": observation.position - source.registration.get("_command_position_base", 0)})
        if observation.position < 1:
            continue  # Pre-registration history cannot establish new acknowledged capture.
        # The existing source IDs are retained, including legacy pair semantics.
        native_source_ids = [event.source_event_id]
        if index > 0 and events[index - 1].event_type == "tool_use" and events[index - 1].call_id == observation.item_id:
            native_source_ids.append(events[index - 1].source_event_id)
        projection = (await db.execute(select(SessionEvent.id).where(SessionEvent.session_id == session.id, SessionEvent.call_id == observation.item_id, SessionEvent.source_event_id.in_(native_source_ids), SessionEvent.event_type.in_(["tool_use", "tool_result"])))).scalars().all()
        await _retain(db, source, observation, [str(identifier) for identifier in projection])
    await _advance(db, source)


async def exclude_projected_rollout_commands(db: AsyncSession, session: Session, events: list[Any]) -> list[Any]:
    """Retain later rollout evidence without replaying an already projected command."""
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    source = next((row for row in sources if row.registration["source_kind"] == "rollout"), None)
    if source is None:
        return events
    excluded = set()
    native_pairs: dict[tuple[int | None, str], set[int]] = {}
    for index, event in enumerate(events):
        if not event.native_observation:
            continue
        observation = NativeObservation.model_validate(event.native_observation)
        if observation.item_id and index > 0 and event.event_type == "tool_result" and events[index - 1].event_type == "tool_use" and events[index - 1].call_id == observation.item_id:
            # The rollout can contain both the tool-call wrapper and its native
            # command item under the exact same native execution ID. Preserve
            # the native pair for projection and retain all lifecycle receipts.
            native_pairs.setdefault((event.turn, observation.item_id), {index - 1, index})
        if observation.history_owner_thread_id not in (None, observation.thread_id):
            observation = observation.model_copy(update={"position": observation.position - source.registration.get("_command_position_base", 0)})
            if observation.position >= 1:
                await _retain(db, source, observation)
            excluded.add(observation.item_id)
            continue
        entity_id = _digest(["codex", source.registration["namespace"], observation.thread_id, observation.turn_id, observation.item_id])
        entity = await db.get(NativeCommandEntity, entity_id)
        if entity is not None and entity.projection_event_ids:
            observation = observation.model_copy(update={"position": observation.position - source.registration.get("_command_position_base", 0)})
            if observation.position >= 1:
                await _retain(db, source, observation)
            excluded.add(observation.item_id)
    await _advance(db, source)
    kept = []
    for index, event in enumerate(events):
        if event.event_type in {"tool_use", "tool_result"}:
            if event.call_id in excluded:
                continue
            pair = native_pairs.get((event.turn, event.call_id))
            if pair is not None and index not in pair:
                # Later native lifecycle receipts still enter the ledger even
                # when their duplicate projection pair is suppressed.
                if event.native_observation:
                    observation = NativeObservation.model_validate(event.native_observation).model_copy(update={"position": NativeObservation.model_validate(event.native_observation).position - source.registration.get("_command_position_base", 0)})
                    if observation.position >= 1:
                        await _retain(db, source, observation)
                continue
        kept.append(event)
    return kept
