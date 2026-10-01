"""Local owner verification, projection control and explicit raw retention."""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    NativeCommandEntity,
    NativeObservationIssue,
    NativeObservationReceipt,
    NativeObservationSource,
    NativeUserIdentity,
    Session,
    SessionEvent,
)
from app.services.event_storage import lock_session_event_ingestion
from app.utils.safe_subprocess import run_process

from .canonical_projection import (
    ACCEPTANCE_CHECKS,
    record_projection_acceptance,
    set_projection_mode,
)
from .native_observations import REQUIRED_CANARY_CASES, native_capture_status

REGISTERED_HOST_PROJECT_ROOT = Path("/srv/workspaces/projects/agent-hub")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _read_receipt(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_size > 10_000_000:
        raise ValueError("Acceptance evidence must be a bounded owner-owned absolute file")
    receipt = json.loads(path.read_text())
    if not isinstance(receipt, dict):
        raise ValueError("Acceptance evidence must be a JSON object")
    return receipt


def _accepted_runtime_source(owner_root: Path) -> dict[str, str] | None:
    """Read source binding only; ST remains the release/acceptance authority."""
    owner_root = owner_root.resolve()
    if owner_root == (REGISTERED_HOST_PROJECT_ROOT / "backend").resolve():
        return None
    source_root = owner_root.parent
    release_root = source_root.parent
    if owner_root.name != "backend" or source_root.name != "source" or release_root.parent.name != "releases":
        raise ValueError("The owner runtime has no managed accepted source binding")
    path = release_root.parent.parent / "receipts" / (release_root.name + ".json")
    try:
        receipt = _read_receipt(path)
    except (OSError, ValueError):
        raise ValueError("The owner runtime source receipt is unavailable or invalid") from None
    source = receipt.get("source")
    if receipt.get("schema_version") != 1 or receipt.get("project") != "agent-hub" or receipt.get("build_id") != release_root.name or receipt.get("source_root") != str(source_root) or not isinstance(source, dict):
        raise ValueError("The owner runtime source receipt does not bind this backend")
    commit, tree = source.get("source_commit"), source.get("source_tree")
    if not isinstance(commit, str) or not commit or not isinstance(tree, str) or not tree:
        raise ValueError("The owner runtime source receipt has no accepted source identity")
    return {"commit": commit, "tree": tree}


def _canonical_gate(owner_root: Path) -> dict[str, Any]:
    runtime_source = _accepted_runtime_source(owner_root)
    if not (REGISTERED_HOST_PROJECT_ROOT / ".git").exists():
        raise ValueError("The registered Agent Hub host checkout is unavailable")
    environment = {key: value for key, value in os.environ.items() if key != "ST_EXTENSION_CONTEXT"}
    # Accepted archives have no Git metadata. Only the canonical host gate uses
    # the checkout; domain actions continue importing the accepted runtime.
    result = run_process(["st", "--no-compact", "check", "--acceptance", "--sha", "HEAD", "--json"], cwd=REGISTERED_HOST_PROJECT_ROOT, env=environment, check=False, capture_output=True, text=True)
    if result.returncode:
        raise ValueError("The current canonical ST acceptance gate failed")
    # The public ST acceptance wire uses a fixed label even with --json.
    receipt = json.loads(result.stdout.removeprefix("ACCEPTANCE:"))
    if not isinstance(receipt, dict):
        raise ValueError("The canonical ST acceptance gate did not return a receipt")
    if runtime_source is not None and receipt.get("source") != runtime_source:
        raise ValueError("The current canonical ST source does not match the accepted owner runtime; rebuild the owner first")
    return receipt


async def verify_acceptance(db: AsyncSession, session: Session, canary: dict[str, Any], identity: dict[str, Any], supplied_gate: dict[str, Any], canonical_gate: dict[str, Any]) -> dict[str, Any]:
    if canonical_gate.get("schema_version") != 1 or canonical_gate.get("kind") != "local_full_acceptance" or canonical_gate.get("state") != "success" or canonical_gate.get("acceptance_id") != supplied_gate.get("acceptance_id") or canonical_gate.get("source") != supplied_gate.get("source"):
        raise ValueError("Acceptance must match the current canonical ST receipt and source")
    if canary.get("external_network") != "absent" or canary.get("provider") != "scripted_loopback_fixture" or any(canary.get("cases", {}).get(key) is not True for key in REQUIRED_CANARY_CASES):
        raise ValueError("The full network-isolated managed runtime canary is required")
    if identity.get("result") != "pass" or identity.get("version") != canary.get("version") or identity.get("external_network") != "absent" or identity.get("credentials") != "absent":
        raise ValueError("The exact isolated native identity proof is required")
    active, resumed, final = (identity.get(key, []) for key in ("active_user_items", "resumed_user_items", "final_user_items"))
    client_id = identity.get("client_user_message_id")
    if not client_id or not active or not resumed or not final or any(item.get("clientId") != client_id for item in [*active, *resumed, *final]) or active[0].get("id") != final[0].get("id") or active[0].get("id") == resumed[0].get("id"):
        raise ValueError("User aliases require the explicit provider client correlation proof")
    sources = (await db.execute(select(NativeObservationSource).where(NativeObservationSource.session_id == session.id))).scalars().all()
    managed = {source.id for source in sources if source.registration.get("source_kind") == "app_server" and source.registration.get("collector_id") == "summitflow/codex-managed" and source.registration.get("provider_version") == canary.get("version") and source.registration.get("schema_fingerprint") == canary.get("schema_fingerprint")}
    rollout = {source.id for source in sources if source.registration.get("source_kind") == "rollout" and source.authenticity == "local_verified"}
    if not managed or not rollout:
        raise ValueError("Acceptance must bind this session's qualified managed and verified rollout sources")
    entities = (await db.execute(select(NativeCommandEntity).where(NativeCommandEntity.session_id == session.id))).scalars().all()
    executed = [entity for entity in entities if entity.status in {"completed", "failed"}]
    if not executed:
        raise ValueError("At least one completed or failed canonical command must be reconciled")
    source_map = {source.id: source for source in sources}
    declined_audit_only = []
    for entity in entities:
        observations = (await db.execute(select(NativeObservationReceipt).where(NativeObservationReceipt.entity_id == entity.id))).scalars().all()
        issue = (await db.execute(select(NativeObservationIssue.id).join(NativeObservationReceipt, (NativeObservationIssue.source_id == NativeObservationReceipt.source_id) & (NativeObservationIssue.position == NativeObservationReceipt.position)).where(NativeObservationReceipt.entity_id == entity.id).limit(1))).scalar_one_or_none()
        if issue is not None or any(receipt.issue_code is not None or receipt.disposition not in {"accounted", "reconciled"} for receipt in observations):
            raise ValueError("Canonical command identity has unresolved receipt issues")
        if entity.status not in {"completed", "failed", "declined"}:
            continue
        receipts = {receipt.source_id for receipt in observations}
        rows = (await db.execute(select(SessionEvent).where(SessionEvent.session_id == session.id, SessionEvent.id.in_(entity.projection_event_ids)))).scalars().all()
        if entity.status == "declined" and not entity.projection_event_ids and not rollout.intersection(receipts):
            # Declined execution can be absent from stored history. Retain its
            # validated native terminal/approval audit, without inventing a pair.
            declined = [receipt for receipt in observations if receipt.source_id in managed and receipt.position <= source_map[receipt.source_id].committed_position and receipt.observation.get("kind") == "app_server_event" and receipt.observation.get("origin") == "live" and receipt.normalized is not None and all(receipt.normalized.get(key) == value for key, value in {"kind": "command_execution", "thread_id": entity.thread_id, "turn_id": entity.turn_id, "item_id": entity.item_id, "command_status": "declined"}.items())]
            requests = (await db.execute(select(NativeObservationReceipt).where(NativeObservationReceipt.source_id.in_({receipt.source_id for receipt in declined}), NativeObservationReceipt.disposition == "retained", NativeObservationReceipt.issue_code.is_(None), NativeObservationReceipt.normalized["kind"].as_string() == "approval_request", NativeObservationReceipt.normalized["thread_id"].as_string() == entity.thread_id, NativeObservationReceipt.normalized["turn_id"].as_string() == entity.turn_id, NativeObservationReceipt.normalized["item_id"].as_string() == entity.item_id, ~select(NativeObservationIssue.id).where(NativeObservationIssue.source_id == NativeObservationReceipt.source_id, NativeObservationIssue.position == NativeObservationReceipt.position).exists()))).scalars().all() if declined else []
            if not any(request.source_id == receipt.source_id and request.position < receipt.position for request in requests for receipt in declined):
                raise ValueError("An audit-only declined command requires validated native terminal and approval evidence")
            declined_audit_only.append(entity.id)
            continue
        if not managed.intersection(receipts) or not rollout.intersection(receipts) or len(rows) != 2 or {row.event_type for row in rows} != {"tool_use", "tool_result"} or any(row.call_id != entity.item_id for row in rows):
            raise ValueError("Canonical command receipts and the single legacy projection pair must match")
    users = (await db.execute(select(NativeUserIdentity).where(NativeUserIdentity.session_id == session.id))).scalars().all()
    if not any(user.durable_item_id and len({alias["item_id"] for alias in user.aliases}) > 1 for user in users):
        raise ValueError("This session must retain attributable provisional user aliases")
    evidence = {"checks": {key: True for key in ACCEPTANCE_CHECKS}, "source_ids": sorted(managed | rollout), "declined_audit_only_entity_ids": sorted(declined_audit_only), "provider_version": canary["version"], "schema_fingerprint": canary["schema_fingerprint"], "canary_sha256": _digest(canary), "identity_sha256": _digest(identity), "acceptance_id": canonical_gate["acceptance_id"], "source": canonical_gate["source"]}
    evidence["evidence_sha256"] = _digest(evidence)
    await record_projection_acceptance(db, session, evidence)
    return {"session_id": session.id, "acceptance_recorded": True, "evidence_sha256": evidence["evidence_sha256"], "promotion_state": "shadow"}


async def prune_raw_evidence(db: AsyncSession, project_id: str, cutoff: datetime, *, limit: int = 100, apply: bool = False) -> dict[str, Any]:
    if cutoff.tzinfo is None or cutoff >= datetime.now(UTC):
        raise ValueError("Retention requires an explicit past cutoff with a timezone")
    from app.services.session_operations import _validate_project_id
    await _validate_project_id(project_id)
    query = select(NativeObservationReceipt, NativeObservationSource).join(NativeObservationSource, NativeObservationReceipt.source_id == NativeObservationSource.id).where(NativeObservationSource.project_id == project_id, NativeObservationReceipt.received_at < cutoff, NativeObservationReceipt.raw_pruned_at.is_(None), NativeObservationReceipt.normalized.is_not(None), NativeObservationReceipt.issue_code.is_(None), NativeObservationReceipt.disposition.in_(["retained", "accounted", "reconciled"]), NativeObservationReceipt.position <= NativeObservationSource.committed_position).order_by(NativeObservationReceipt.source_id, NativeObservationReceipt.position).limit(limit)
    if apply:
        await lock_session_event_ingestion(db, "native-retention:" + project_id)
    rows = (await db.execute(query)).all()
    pruned = 0
    if apply:
        for receipt, source in rows:
            await lock_session_event_ingestion(db, source.session_id or source.id)
            await db.refresh(receipt)
            if receipt.raw_pruned_at is None:
                receipt.observation = {**receipt.observation, "payload": {"raw_pruned": True}}
                receipt.raw_pruned_at = datetime.now(UTC)
                pruned += 1
        await db.commit()
    return {"project_id": project_id, "cutoff": cutoff.isoformat(), "eligible": len(rows), "pruned": pruned, "applied": apply, "protected": ["pending", "unresolved", "unsupported", "quarantined", "conflict"], "ledger_preserved": True}


async def run_native_operator(action: str, *, owner_root: Path, session_id: str | None = None, **arguments: Any) -> dict[str, Any]:
    from app.db import _get_session_factory
    canonical_gate = None
    evidence = None
    if action == "acceptance":
        evidence = [_read_receipt(arguments[key]) for key in ("canary_receipt", "identity_receipt", "gate_receipt")]
        canonical_gate = await asyncio.to_thread(_canonical_gate, owner_root)
    async with _get_session_factory()() as db:
        if action == "prune_raw":
            return await prune_raw_evidence(db, arguments["project_id"], datetime.fromisoformat(arguments["older_than"].replace("Z", "+00:00")), limit=arguments["limit"], apply=arguments["apply"])
        session = await db.get(Session, session_id)
        if session is None:
            raise ValueError("Native session not found")
        if action == "status":
            return await native_capture_status(db, session)
        if action == "projection":
            return await set_projection_mode(db, session, arguments["mode"])
        if action == "acceptance" and evidence and canonical_gate:
            return await verify_acceptance(db, session, evidence[0], evidence[1], evidence[2], canonical_gate)
        raise ValueError("Unknown native owner operation")
