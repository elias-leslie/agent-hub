"""Canonical native receipts and shadow reconciliation under the session ingest lock."""

import asyncio
import json
import shlex
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    NativeObservationSource,
    NativeProtocolProfile,
    NativeUserIdentity,
    Session,
)
from app.services.event_storage import lock_session_event_ingestion

from .adapters._event_builders import _native_shell_command
from .app_server_observations import (
    SUPPORTED_VERSIONS,
    interpret_wire,
    json_digest,
    protocol_contract,
)
from .native_models import (
    NativeObservation,
    NativeObservationBatch,
    NativeObservationDisposition,
    NativeObservationResult,
    NativeProtocolProfileRegistration,
    NativeQuarantineBatch,
    NativeQuarantineRegistration,
    NativeSourceReceipt,
    NativeSourceRegistration,
)
from .service import SessionIngestionConflict


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
    qualified_profile = await db.get(NativeProtocolProfile, request.provider_version)
    if qualified_profile and qualified_profile.schema_fingerprint == request.schema_fingerprint:
        registration["_protocol_profile_version"] = qualified_profile.reference_profile_version
    # Include the execution binding so epochs cannot alias across child sessions.
    identity = [session.id, request.namespace, request.source_kind, request.producer_id, request.epoch]
    if request.generation:
        identity.append(request.generation)
    source_id = json_digest(identity)
    if request.generation:
        previous = await db.get(NativeObservationSource, request.predecessor_source_id) if request.predecessor_source_id else None
        if previous is None or previous.session_id != session.id or any(previous.registration.get(key) != registration.get(key) for key in ("namespace", "source_kind", "producer_id", "epoch")) or previous.registration.get("generation", 0) + 1 != request.generation:
            raise SessionIngestionConflict("native_source_generation_mismatch", "A generation requires the exact preceding source binding.")
    elif request.predecessor_source_id:
        raise SessionIngestionConflict("native_source_generation_mismatch", "The initial generation cannot name a predecessor.")
    source = await db.get(NativeObservationSource, source_id)
    new_source = source is None
    if source is not None and NativeSourceRegistration.model_validate({key: value for key, value in source.registration.items() if not key.startswith("_")}).model_dump(mode="json") != {key: value for key, value in registration.items() if not key.startswith("_")}:
        raise SessionIngestionConflict("native_source_registration_conflict", "An existing producer epoch has different registration evidence.")
    if source is None:
        if request.source_kind == "rollout":
            from .adapters.transcript_parsers import _load_parse_checkpoint

            other_sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
            if any(row.registration["source_kind"] == "rollout" for row in other_sources) and not request.generation:
                raise SessionIngestionConflict("native_rollout_source_already_registered", "Additional rollout sources require an explicit successor generation.")
            retained = metadata.get("transcript_ingestion") or {}
            registration["_command_position_base"] = 0 if request.reconcile_existing_rollout else _load_parse_checkpoint(retained.get("checkpoint")).codex_model_state.get("command_position", 0)
        source = NativeObservationSource(id=source_id, session_id=session.id, project_id=session.project_id, registration=registration, authenticity=authenticity, committed_position=0)
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
    key = json_digest([source_id, observation.position, code, payload])
    if await db.get(NativeObservationIssue, key) is None:
        db.add(NativeObservationIssue(id=key, source_id=source_id, position=observation.position, code=code, observation=payload))
        await db.flush()


async def approval_subject(db: AsyncSession, source_id: str, observation: NativeObservation) -> dict[str, Any] | None:
    """Resolve only exact request IDs within this source/connection and thread."""
    wire = observation.payload
    request_id = wire.get("request_id") if observation.kind == "approval_response" else wire.get("params", {}).get("requestId") if wire.get("method") == "serverRequest/resolved" else None
    if not isinstance(request_id, (int, str)) or isinstance(request_id, bool):
        return None
    query = select(NativeObservationReceipt).where(NativeObservationReceipt.source_id == source_id, NativeObservationReceipt.position < observation.position, or_(cast(NativeObservationReceipt.observation["payload"]["id"], String) == json.dumps(request_id), cast(NativeObservationReceipt.normalized["approval_request"]["request_id"], String) == json.dumps(request_id)))
    connection_id = observation.source_reference.get("connection_id")
    query = query.where(NativeObservationReceipt.observation["source_reference"]["connection_id"].as_string() == connection_id)
    prior = (await db.execute(query.order_by(NativeObservationReceipt.position.desc()).limit(1))).scalar_one_or_none()
    if prior is None or prior.disposition != "retained" or prior.issue_code is not None:
        return None
    audit = (prior.normalized or {}).get("approval_request")
    if isinstance(audit, dict):
        return {**audit, "source_id": source_id, "request_position": prior.position}
    if not prior.observation["payload"].get("method", "").endswith("/requestApproval"):
        return None
    params = prior.observation["payload"]["params"]
    return {"source_id": source_id, "request_position": prior.position, "request_id": request_id, "thread_id": params["threadId"], "turn_id": params.get("turnId"), "item_id": params.get("itemId"), "connection_id": connection_id}


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
    payload_hash = json_digest(payload)
    existing = await db.get(NativeObservationReceipt, (source.id, observation.position))
    if existing is not None:
        if existing.payload_hash != payload_hash:
            await _issue(db, source.id, observation, "receipt_payload_conflict")
            return NativeObservationDisposition(position=observation.position, disposition="conflict", issue_code="receipt_payload_conflict")
        if projection_event_ids and existing.entity_id and existing.disposition in {"accounted", "reconciled"}:
            entity = await db.get(NativeCommandEntity, existing.entity_id)
            if entity is not None:
                entity.projection_event_ids = list(dict.fromkeys([*entity.projection_event_ids, *projection_event_ids]))
        return NativeObservationDisposition(position=observation.position, disposition="replayed", entity_id=existing.entity_id, issue_code=existing.issue_code)
    original_observation = observation
    observation, wire_issue = await asyncio.to_thread(interpret_wire, observation, source.registration)
    subject = None
    if observation.kind in {"approval_response", "approval_resolution"}:
        subject = await approval_subject(db, source.id, original_observation)
        if subject is None:
            wire_issue = "approval_request_unavailable"
        elif subject["thread_id"] != observation.thread_id or (observation.kind == "approval_response" and (observation.source_reference.get("turn_id") != subject["turn_id"] or observation.source_reference.get("item_id") != subject["item_id"])):
            wire_issue = "approval_subject_mismatch"
        if subject is not None:
            observation = observation.model_copy(update={"source_reference": {**observation.source_reference, "approval_request_position": subject["request_position"]}})
    disposition, code, entity_id = "unresolved", None, None
    snapshot_users = []
    if observation.history_owner_thread_id not in (None, observation.thread_id):
        disposition, code = "inherited", "inherited_history"
    elif wire_issue:
        disposition, code = "unsupported", wire_issue
    elif observation.kind == "capture_health":
        if observation.payload.get("state") in {"initialized", "connected", "capture_gap", "disabled", "unsupported", "outbox_full", "disconnected"}:
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unsupported_capture_health"
    elif observation.kind == "approval_response" and wire_issue is None:
        disposition = "retained"
    elif observation.kind == "app_server_configuration":
        configuration = observation.payload
        if configuration.get("direction") in {"request", "response"} and configuration.get("method") in {"thread/start", "thread/fork", "thread/resume", "turn/start", "thread/settings/update", "turn/steer"} and isinstance(configuration.get("params"), dict) and all(key in {"model", "effort", "reasoningEffort", "clientUserMessageId"} and (value is None or isinstance(value, str)) for key, value in configuration["params"].items()):
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unsupported_configuration_shape"
    elif observation.kind == "app_server_snapshot":
        from .native_user_aliases import correlate_snapshot_users
        snapshot_users, code = await correlate_snapshot_users(db, source, observation)
        disposition = "retained" if code is None else "inherited" if code == "inherited_history" else "conflict" if code == "native_user_identity_conflict" else "unresolved"
    elif observation.kind == "user_message" and payload["kind"] != "app_server_event":
        disposition, code = "unsupported", "unverified_app_server_evidence"
    elif observation.kind == "user_message":
        from .native_user_aliases import correlate_live_user
        snapshot_users, code = await correlate_live_user(db, source, observation)
        disposition = "retained" if code is None else "conflict" if code == "native_user_identity_conflict" else "unresolved"
    elif observation.kind in {"lifecycle", "approval_request", "approval_resolution", "usage_snapshot"}:
        # These are derived exclusively from validated wire evidence. They do not
        # append commands, token deltas, or grant any execution/approval authority.
        if payload["kind"] == "app_server_event":
            disposition = "retained"
        else:
            disposition, code = "unsupported", "unverified_app_server_evidence"
    elif observation.kind != "command_execution":
        disposition, code = "unsupported", "unsupported_observation_kind"
    elif source.registration["source_kind"] == "app_server" and payload["kind"] != "app_server_event":
        disposition, code = "unsupported", "unverified_app_server_evidence"
    elif observation.identity_quality != "durable" or observation.origin == "active_resume_snapshot":
        code = "provisional_identity"
    elif not observation.turn_id or not observation.item_id:
        code = "missing_native_identity"
    elif (parsed := _command(observation)) is None:
        disposition, code = "unsupported", "unsupported_command_shape"
    else:
        status, command = parsed
        entity_id = json_digest(["codex", source.registration["namespace"], observation.thread_id, observation.turn_id, observation.item_id])
        entity = await db.get(NativeCommandEntity, entity_id)
        output_hashes = _terminal_output_hashes(observation) if status in {"completed", "failed", "declined"} and source.registration["source_kind"] == "app_server" else {}
        previous_output_hashes = (entity.command.get("_terminal_output_hashes", {}).get(source.id, {}) if entity else {})
        output_conflict = any(previous_output_hashes[key] != value for key, value in output_hashes.items() if key in previous_output_hashes)
        if entity is None:
            if output_hashes:
                command["_terminal_output_hashes"] = {source.id: output_hashes}
            entity = NativeCommandEntity(id=entity_id, session_id=source.session_id, namespace=source.registration["namespace"], thread_id=observation.thread_id, turn_id=observation.turn_id, item_id=observation.item_id, status=status, command=command, projection_event_ids=projection_event_ids or [], observed_model=None)
            db.add(entity)
            disposition = "accounted"
        elif output_conflict:
            disposition, code = "conflict", "entity_terminal_output_conflict"
        elif any(entity.command[key] != value for key, value in command.items() if key in entity.command):
            disposition, code = "conflict", "entity_payload_conflict"
        elif entity.status in {"completed", "failed", "declined"} and status in {"completed", "failed", "declined"} and status != entity.status:
            disposition, code = "conflict", "entity_terminal_conflict"
        else:
            disposition = "reconciled"
            if entity.status == "running":
                entity.status = status
            entity.command = {**command, **entity.command}
            if output_hashes:
                entity.command = {**entity.command, "_terminal_output_hashes": {**entity.command.get("_terminal_output_hashes", {}), source.id: {**previous_output_hashes, **output_hashes}}}
            if projection_event_ids:
                entity.projection_event_ids = list(dict.fromkeys([*entity.projection_event_ids, *projection_event_ids]))
        await db.flush()
    normalized = _normalized_view(observation, disposition, subject)
    if snapshot_users and normalized is not None:
        normalized.update({"user_aliases": snapshot_users, "snapshot_scope": "user_aliases_only", "live_completeness": False})
    if disposition in {"retained", "accounted", "reconciled"} and source.registration.get("source_kind") == "app_server":
        from .canonical_projection import project_live_observation
        session = await db.get(Session, source.session_id)
        entity = await db.get(NativeCommandEntity, entity_id) if entity_id else None
        if session is not None:
            projected = await project_live_observation(db, session, source, observation, entity)
            if projected and normalized is not None:
                normalized["projection_event_ids"] = projected
    receipt = NativeObservationReceipt(source_id=source.id, position=observation.position, payload_hash=payload_hash, observation=payload, normalized=normalized, disposition=disposition, issue_code=code, entity_id=entity_id)
    db.add(receipt)
    if code:
        await _issue(db, source.id, original_observation, code)
    await db.flush()
    return NativeObservationDisposition(position=observation.position, disposition=disposition, entity_id=entity_id, issue_code=code)


async def native_capture_status(db: AsyncSession, session: Session) -> dict[str, Any]:
    """Content-free, durable health. Queries never contact a native runtime."""
    from sqlalchemy import func

    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    from .canonical_projection import projection_status
    promotion = await projection_status(db, session)
    health = []
    for source in sources:
        count, maximum, latest = (await db.execute(select(func.count(), func.max(NativeObservationReceipt.position), func.max(NativeObservationReceipt.received_at)).where(NativeObservationReceipt.source_id == source.id))).one()
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
        profile_version = source.registration.get("_protocol_profile_version", source.registration["provider_version"])
        protocol_supported = source.registration["source_kind"] == "rollout" or (profile_version in SUPPORTED_VERSIONS and source.registration["schema_fingerprint"] == protocol_contract(profile_version)[0])
        dispositions = {kind: count for kind, count in (await db.execute(select(NativeObservationReceipt.disposition, func.count()).where(NativeObservationReceipt.source_id == source.id).group_by(NativeObservationReceipt.disposition))).all()}
        age = (datetime.now(UTC) - latest).total_seconds() if latest else None
        freshness = "never_observed" if age is None else "stale" if age > 300 else "recent"
        health.append({"protocol_supported": protocol_supported, "compatibility": "compatible" if protocol_supported else "incompatible", "generation": source.registration.get("generation", 0), "parser_generation": source.registration.get("_parser_generation", 0), "projection_mode": promotion["promotion_state"], "last_received_at": latest.isoformat() if latest else None, "freshness": freshness, "dispositions": dispositions, "source_id": source.id, "kind": source.registration["source_kind"], "provider_version": source.registration["provider_version"], "schema_fingerprint": source.registration["schema_fingerprint"], "authenticity": source.authenticity, "committed_position": source.committed_position, "receipt_count": count, "max_position": maximum or 0, "first_missing_position": source.committed_position + 1 if (maximum or 0) > source.committed_position else None, "issues": {code: n for code, n in issues}, "capture_health": public_health})
    return {**promotion, "schema_version": "native-observation.v1", "session_id": session.id, "capture_mode": "app_server_registered" if any(row.registration["source_kind"] == "app_server" for row in sources) else "rollout_only", "supported_provider_versions": list(SUPPORTED_VERSIONS), "delivery_status": "collector_reported_only", "observed_model": None, "raw_retention": "owner_policy_required", "sources": health}


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
    source = max((row for row in sources if row.registration.get("source_kind") == "rollout"), key=lambda row: (row.registration.get("generation", 0), row.registration.get("_parser_generation", 0)), default=None)
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
    source = max((row for row in sources if row.registration.get("source_kind") == "rollout"), key=lambda row: (row.registration.get("generation", 0), row.registration.get("_parser_generation", 0)), default=None)
    if source is None:
        return events
    excluded = set()
    projected_types: dict[str, set[str]] = {}
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
        entity_id = json_digest(["codex", source.registration["namespace"], observation.thread_id, observation.turn_id, observation.item_id])
        entity = await db.get(NativeCommandEntity, entity_id)
        if entity is not None and entity.projection_event_ids:
            observation = observation.model_copy(update={"position": observation.position - source.registration.get("_command_position_base", 0)})
            if observation.position >= 1:
                retained = await _retain(db, source, observation)
                if retained.disposition != "conflict" and not retained.issue_code and index > 0 and events[index - 1].event_type == "tool_use":
                    from .canonical_projection import align_rollout_projection
                    await align_rollout_projection(db, session, entity, [events[index - 1], event])
            from app.models import SessionEvent
            projected_rows = (await db.execute(select(SessionEvent.event_type).where(SessionEvent.session_id == session.id, SessionEvent.id.in_(entity.projection_event_ids)))).scalars().all()
            if observation.item_id is not None:
                projected_types[observation.item_id] = set(projected_rows)
    await _advance(db, source)
    kept = []
    for index, event in enumerate(events):
        if event.event_type in {"tool_use", "tool_result"}:
            if event.call_id in excluded or event.event_type in projected_types.get(event.call_id, set()):
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


async def register_native_quarantine(db: AsyncSession, request: NativeQuarantineRegistration) -> NativeSourceReceipt:
    from app.services.session_operations import _validate_project_id

    await _validate_project_id(request.project_id)
    registration = request.model_dump(mode="json")
    source_id = json_digest(["quarantine", request.project_id, request.namespace, request.producer_id, request.epoch, request.generation])
    await lock_session_event_ingestion(db, source_id)
    source = await db.get(NativeObservationSource, source_id)
    if source is not None and source.registration != registration:
        raise SessionIngestionConflict("native_source_registration_conflict", "The quarantine stream has different registration evidence.")
    if source is None:
        source = NativeObservationSource(id=source_id, session_id=None, project_id=request.project_id, registration=registration, authenticity="collector_attested", committed_position=0)
        db.add(source)
    await db.commit()
    return NativeSourceReceipt(source_id=source.id, committed_position=source.committed_position, authenticity=source.authenticity)


async def ingest_native_quarantine(db: AsyncSession, source: NativeObservationSource, request: NativeQuarantineBatch) -> NativeObservationResult:
    if source.session_id is not None:
        raise SessionIngestionConflict("native_quarantine_source_mismatch", "The source is bound to a session.")
    await lock_session_event_ingestion(db, source.id)
    await db.refresh(source)
    dispositions = []
    for observation in request.observations:
        payload = observation.model_dump(mode="json")
        digest = json_digest(payload)
        prior = await db.get(NativeObservationReceipt, (source.id, observation.position))
        disposition, code = "quarantined", "unbound_native_subject"
        if prior:
            disposition = "replayed" if prior.payload_hash == digest else "conflict"
            code = prior.issue_code if disposition == "replayed" else "receipt_payload_conflict"
        else:
            db.add(NativeObservationReceipt(source_id=source.id, position=observation.position, payload_hash=digest, observation=payload, disposition=disposition, issue_code=code))
        if disposition != "replayed":
            issue_id = json_digest([source.id, observation.position, code, payload])
            if await db.get(NativeObservationIssue, issue_id) is None:
                db.add(NativeObservationIssue(id=issue_id, source_id=source.id, position=observation.position, code=code, observation=payload))
        await db.flush()
        dispositions.append(NativeObservationDisposition(position=observation.position, disposition=disposition, issue_code=code))
    await _advance(db, source)
    await db.commit()
    return NativeObservationResult(source_id=source.id, committed_position=source.committed_position, authenticity=source.authenticity, dispositions=dispositions)


async def prepare_rollout_source_generation(db: AsyncSession, session: Session, events: list[Any]) -> None:
    """A parser restart cannot reuse source positions from an earlier file generation."""
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    previous = max((row for row in sources if row.registration.get("source_kind") == "rollout"), key=lambda row: (row.registration.get("generation", 0), row.registration.get("_parser_generation", 0)), default=None)
    if previous is None:
        return
    rotate = False
    for event in events:
        if not event.native_observation:
            continue
        raw = NativeObservation.model_validate(event.native_observation)
        position = raw.position - previous.registration.get("_command_position_base", 0)
        if position < 1:
            # Reset below a registration baseline is also a new parser generation.
            rotate = True
            break
        retained = await db.get(NativeObservationReceipt, (previous.id, position))
        if retained and retained.observation.get("source_reference") != raw.source_reference:
            rotate = True
            break
    if not rotate:
        return
    registration = dict(previous.registration)
    parser_generation = registration.get("_parser_generation", 0) + 1
    registration_source_id = registration.get("_registration_source_id", previous.id)
    registration.update({"_parser_generation": parser_generation, "_registration_source_id": registration_source_id, "_parser_predecessor_source_id": previous.id, "_command_position_base": 0, "_rotation_reason": "local_parser_generation_changed"})
    source_id = json_digest(["rollout-parser", registration_source_id, parser_generation])
    db.add(NativeObservationSource(id=source_id, session_id=session.id, project_id=session.project_id, registration=registration, authenticity="local_verified", committed_position=0))
    await db.flush()


async def native_evidence_summary(db: AsyncSession, session: Session, *, after_entity_id: str = "", limit: int = 100) -> dict[str, Any]:
    """Bounded project-visible provenance and approval binding without raw evidence."""
    from sqlalchemy import func

    entities = (await db.execute(select(NativeCommandEntity).where(NativeCommandEntity.session_id == session.id, NativeCommandEntity.id > after_entity_id).order_by(NativeCommandEntity.id).limit(limit))).scalars().all()
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    source_map = {row.id: row for row in sources}
    source_ids = list(source_map)
    receipts = (await db.execute(select(NativeObservationReceipt.source_id, NativeObservationReceipt.position, NativeObservationReceipt.entity_id, NativeObservationReceipt.observation["origin"].as_string().label("origin"), NativeObservationReceipt.disposition).where(NativeObservationReceipt.source_id.in_(source_ids), NativeObservationReceipt.entity_id.in_([entity.id for entity in entities])).order_by(NativeObservationReceipt.source_id, NativeObservationReceipt.position).limit(10000))).all() if entities else []
    commands = []
    for entity in entities:
        evidence = [{"source_id": row.source_id, "position": row.position, "source_kind": source_map[row.source_id].registration["source_kind"], "authenticity": source_map[row.source_id].authenticity, "origin": row.origin, "disposition": row.disposition} for row in receipts if row.entity_id == entity.id]
        commands.append({"entity_id": entity.id, "projection_event_ids": entity.projection_event_ids, "status": entity.status, "observed_model": entity.observed_model, "receipts": evidence})
    base = NativeObservationReceipt.source_id.in_(source_ids)
    async def count_condition(condition: Any) -> int:
        return (await db.execute(select(func.count()).select_from(NativeObservationReceipt).where(base, condition))).scalar_one()
    method = NativeObservationReceipt.observation["payload"]["method"].as_string()
    retained = NativeObservationReceipt.disposition == "retained"
    approvals = {
        "validated_requests": await count_condition(retained & (method.endswith("/requestApproval") | (NativeObservationReceipt.normalized["kind"].as_string() == "approval_request"))),
        "bound_responses": await count_condition(retained & (NativeObservationReceipt.observation["kind"].as_string() == "approval_response")),
        "cleared_requests": await count_condition(retained & ((method == "serverRequest/resolved") | (NativeObservationReceipt.normalized["kind"].as_string() == "approval_resolution"))),
        "unresolved": await count_condition(NativeObservationReceipt.issue_code.in_(["approval_request_unavailable", "approval_subject_mismatch"])),
    }
    users = (await db.execute(select(NativeUserIdentity).where(NativeUserIdentity.session_id == session.id).order_by(NativeUserIdentity.id).limit(limit))).scalars().all()
    user_summaries = [{"entity_id": user.id, "native_turn_id": user.turn_id, "canonical_item_id": user.durable_item_id, "correlation": "explicit_provider_client_id", "live_verified": user.live_verified, "aliases": user.aliases[:100], "projection_event_ids": user.projection_event_ids} for user in users]
    return {"schema_version": "native-observation.v1", "session_id": session.id, "commands": commands, "users": user_summaries, "next_entity_id": entities[-1].id if entities else after_entity_id, "provenance_truncated": len(receipts) == 10000, "inherited_receipt_count": await count_condition(NativeObservationReceipt.disposition == "inherited"), "unresolved_receipt_count": await count_condition(NativeObservationReceipt.disposition == "unresolved"), "approvals": approvals, "usage_authority": "rollout", "observed_model": None}


def _normalized_view(observation: NativeObservation, disposition: str, subject: dict[str, Any] | None) -> dict[str, Any] | None:
    """Persist validated canonical views; usage remains a non-additive snapshot."""
    if disposition not in {"retained", "accounted", "reconciled"}:
        return None
    view: dict[str, Any] = {"kind": observation.kind, "thread_id": observation.thread_id, "turn_id": observation.turn_id, "item_id": observation.item_id}
    if observation.kind == "usage_snapshot":
        view.update({"usage": observation.payload.get("tokenUsage"), "accounting": "cumulative_snapshot", "billing_authority": False})
    elif observation.kind == "lifecycle":
        turn = observation.payload.get("turn")
        thread = observation.payload.get("thread")
        if isinstance(turn, dict):
            view["turn_status"] = turn.get("status")
        if isinstance(thread, dict):
            view["thread_status"] = thread.get("status")
    elif observation.kind in {"approval_response", "approval_resolution"}:
        view.update({"approval_subject": subject, "approval_state": "client_responded" if observation.kind == "approval_response" else "request_cleared"})
    elif observation.kind == "approval_request":
        view["approval_state"] = "requested"
        view["approval_request"] = {"request_id": observation.source_reference.get("request_id"), "thread_id": observation.thread_id, "turn_id": observation.turn_id, "item_id": observation.item_id, "connection_id": observation.source_reference.get("connection_id"), "request_position": observation.position}
    elif observation.kind == "command_execution":
        parsed = _command(observation)
        view["command_status"] = parsed[0] if parsed else None
    model_evidence = {"requested_model": observation.requested_model, "requested_reasoning_effort": observation.requested_reasoning_effort, "configured_model": observation.configured_model, "observed_model": None}
    if observation.kind == "app_server_configuration":
        params = observation.payload.get("params", {})
        if observation.payload.get("direction") == "request":
            model_evidence.update({"requested_model": params.get("model"), "requested_reasoning_effort": params.get("effort", params.get("reasoningEffort"))})
        elif observation.payload.get("direction") == "response":
            model_evidence["configured_model"] = params.get("model")
        if "clientUserMessageId" in params:
            view["requested_client_user_message_id"] = params["clientUserMessageId"]
    view["model_evidence"] = model_evidence
    return view


REQUIRED_CANARY_CASES = ("completed_command", "live_approval_request_resolution", "turn_interruption_resume", "compaction", "fork_snapshot", "native_child", "owned_child_subscription", "supervisor_restart_resume", "usage_snapshots", "runtime_rollback_to_rollout", "safe_runtime_reenable", "process_owner_fencing", "external_thread_rejection", "quota_preserves_native_execution", "exact_client_message_identity")


async def qualify_native_protocol_profile(db: AsyncSession, request: NativeProtocolProfileRegistration) -> dict[str, Any]:
    """Only the evidence owner can qualify an identical tested schema after a full canary."""
    receipt = request.canary_receipt
    candidates = [version for version in SUPPORTED_VERSIONS if protocol_contract(version)[0] == request.schema_fingerprint]
    cases = receipt.get("cases", {})
    if not candidates or receipt.get("version") != request.provider_version or receipt.get("schema_fingerprint") != request.schema_fingerprint or receipt.get("external_network") != "absent" or receipt.get("provider") != "scripted_loopback_fixture" or not isinstance(receipt.get("provider_requests"), int) or isinstance(receipt.get("provider_requests"), bool) or receipt["provider_requests"] < 1 or not isinstance(cases, dict) or any(cases.get(key) is not True for key in REQUIRED_CANARY_CASES):
        raise SessionIngestionConflict("native_protocol_qualification_failed", "Qualification requires an identical tested schema and the exact complete isolated canary receipt.")
    await lock_session_event_ingestion(db, "native-protocol:" + request.provider_version)
    digest = json_digest(receipt)
    profile = await db.get(NativeProtocolProfile, request.provider_version)
    if profile is not None:
        if profile.schema_fingerprint != request.schema_fingerprint:
            raise SessionIngestionConflict("native_protocol_profile_immutable", "A qualified version cannot be rebound to different evidence.")
    else:
        profile = NativeProtocolProfile(provider_version=request.provider_version, schema_fingerprint=request.schema_fingerprint, reference_profile_version=candidates[-1], canary_sha256=digest, canary_receipt=receipt)
        db.add(profile)
    await db.commit()
    return {"provider_version": profile.provider_version, "schema_fingerprint": profile.schema_fingerprint, "reference_profile_version": profile.reference_profile_version, "canary_sha256": profile.canary_sha256, "qualified": True}


async def list_native_protocol_profiles(db: AsyncSession) -> dict[str, Any]:
    profiles = (await db.execute(select(NativeProtocolProfile).order_by(NativeProtocolProfile.provider_version))).scalars().all()
    return {"profiles": [{"provider_version": version, "schema_fingerprint": protocol_contract(version)[0], "reference_profile_version": version, "qualified": True, "bundled": True} for version in SUPPORTED_VERSIONS] + [{"provider_version": row.provider_version, "schema_fingerprint": row.schema_fingerprint, "reference_profile_version": row.reference_profile_version, "canary_sha256": row.canary_sha256, "qualified": True, "bundled": False} for row in profiles]}


def _terminal_output_hashes(observation: NativeObservation) -> dict[str, str]:
    item = observation.payload.get("item", {})
    return {key: json_digest(value) for key, value in item.items() if key in {"stdout", "stderr", "aggregatedOutput"} and isinstance(value, str)}
