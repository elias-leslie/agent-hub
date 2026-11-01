"""context_deliveries: record a delivery when it is built, import history from delivery contract files, bind sessions.

`record_delivery` is called by the real delivery sites (build_canonical_context_delivery(..., record=True)), never by
previews or dry runs. It uses its own short session and never raises into the delivery. The importer reads the
contract files the thin clients keep (one JSON per delivery) so history before recording began is queryable too; both
paths key on the canonical delivery_id, so a delivery that exists in both is one row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContextDelivery
from app.utils.native_homes import native_homes

logger = logging.getLogger(__name__)

CONTRACT_SCHEMA = "agent-hub.context.v1"
INSERT_CHUNK = 500
BIND_WINDOW_BEFORE = timedelta(hours=24)  # a delivery is built shortly before its session's first call
BIND_WINDOW_AFTER = timedelta(minutes=5)
WORK_ROLE_PREFIX = "work-role:"
COORDINATOR_TAG = "aico-coordinator"

_VALUE_KEYS = (
    "delivery_id", "generated_at", "source", "surface", "profile", "project_id", "session_id", "agent_slug", "work_role",
    "coordinator", "consumer_tags", "model", "provider", "host", "est_tokens", "payload_hash", "rendered_chars",
    "by_scope", "blocks",
)


def delivery_roots() -> list[Path]:
    if configured := os.environ.get("AGENT_HUB_CONTEXT_ARTIFACT_ROOT"):
        return [Path(configured).expanduser()]
    return [home / ".local" / "state" / "agent-hub" / "context-deliveries" for home in native_homes()]


def role_from_tags(tags: Iterable[str]) -> tuple[str | None, bool]:
    """(work_role, coordinator) of a delivery's consumer tags. No work-role tag and not a coordinator: (None, False)."""
    tag_list = [t for t in tags if isinstance(t, str)]
    role = next((t[len(WORK_ROLE_PREFIX):] for t in tag_list if t.startswith(WORK_ROLE_PREFIX)), None)
    coordinator = COORDINATOR_TAG in tag_list or role == "coordinator"
    return (role or ("coordinator" if coordinator else None)), coordinator


def block_rows(blocks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for block in blocks:
        prov = block.get("provenance") or {}
        out.append({
            "block_id": block.get("block_id"), "kind": block.get("kind"), "source_type": prov.get("source_type"),
            "source_id": prov.get("source_id"), "revision": prov.get("source_revision"), "scope": prov.get("scope"),
            "tokens": int(block.get("estimated_tokens") or 0),
        })
    return out


def scope_tokens(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = row.get("scope") or "none"
        out[key] = out.get(key, 0) + int(row.get("tokens") or 0)
    return out


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def values_from_contract(contract: dict[str, Any], *, source: str) -> dict[str, Any] | None:
    """Row values for a canonical delivery (a response dumped to JSON, or a client contract file). None if unusable."""
    if not isinstance(contract, dict) or contract.get("status") not in (None, "ok") or contract.get("failure"):
        return None
    delivery_id = contract.get("delivery_id")
    payload_hash = contract.get("payload_hash")
    generated = _parse_dt(contract.get("generated_at"))
    meta = contract.get("metadata") or {}
    if not delivery_id or not payload_hash or generated is None or not meta.get("consumer_surface"):
        return None
    tags = [t for t in meta.get("consumer_tags") or [] if isinstance(t, str)]
    role, coordinator = role_from_tags(tags)
    rows = block_rows(contract.get("blocks") or [])
    client_meta = meta.get("client_metadata") or {}
    return {
        "delivery_id": str(delivery_id)[:64], "generated_at": generated, "source": source,
        "surface": str(meta["consumer_surface"])[:100], "profile": (meta.get("consumer_profile") or None) and str(meta["consumer_profile"])[:100],
        "project_id": meta.get("project_id"), "session_id": (meta.get("session_id") or None) and str(meta["session_id"])[:200],
        "agent_slug": meta.get("agent_slug"), "work_role": role, "coordinator": coordinator, "consumer_tags": tags,
        "model": (meta.get("model") or None) and str(meta["model"])[:200], "provider": meta.get("provider"),
        "host": client_meta.get("remote_host") or None, "est_tokens": int(contract.get("estimated_tokens") or 0),
        "payload_hash": str(payload_hash)[:64], "rendered_chars": len(contract.get("rendered") or ""),
        "by_scope": scope_tokens(rows), "blocks": rows,
    }


async def _insert(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    inserted = 0
    for i in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[i:i + INSERT_CHUNK]
        stmt = pg_insert(ContextDelivery).values(chunk).on_conflict_do_nothing(index_elements=["delivery_id"])
        result = await db.execute(stmt)
        inserted += cast(CursorResult[Any], result).rowcount or 0
    return inserted


def _contract_view(response: Any) -> dict[str, Any]:
    """The few fields of a built delivery the row needs, without dumping its preview projection or block text."""
    return {
        "delivery_id": response.delivery_id, "payload_hash": response.payload_hash, "generated_at": response.generated_at,
        "status": response.status, "failure": response.failure, "estimated_tokens": response.estimated_tokens,
        "rendered": response.rendered, "metadata": response.metadata.model_dump(mode="json"),
        "blocks": [b.model_dump(mode="json", exclude={"content"}) for b in response.blocks],
    }


async def record_delivery(response: Any, *, source: str) -> None:
    """Store one built delivery. Own session; a recording failure is logged and never reaches the delivery."""
    try:
        from app.db import async_session

        values = values_from_contract(_contract_view(response), source=source)
        if values is None:
            return
        async with async_session() as db:
            await _insert(db, [values])
            await db.commit()
    except Exception:
        logger.warning("context delivery not recorded", exc_info=True)


def _contract_files(root: Path, since: float) -> list[Path]:
    out: list[Path] = []
    try:
        surfaces = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for surface in surfaces:
        for path in surface.glob("*/*/*.json"):
            try:
                if path.stat().st_mtime >= since:
                    out.append(path)
            except OSError:
                continue
    return out


def import_contract_values(roots: Iterable[Path], *, since: datetime) -> list[dict[str, Any]]:
    """Row values from every delivery contract file written since `since` (blocking: run in a thread)."""
    rows: dict[str, dict[str, Any]] = {}
    for root in roots:
        for path in _contract_files(root, since.timestamp()):
            try:
                contract = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if not isinstance(contract, dict) or contract.get("schema_version") != CONTRACT_SCHEMA:
                continue
            values = values_from_contract(contract, source="file")
            if values and values["generated_at"] >= since:
                rows.setdefault(values["delivery_id"], values)
    return list(rows.values())


async def import_delivery_files(db: AsyncSession, *, since: datetime, roots: Iterable[Path] | None = None) -> int:
    """Insert deliveries from contract files written since `since` that are not stored yet. Returns rows added."""
    import asyncio

    values = await asyncio.to_thread(import_contract_values, list(roots if roots is not None else delivery_roots()), since=since)
    return await _insert(db, values)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _row_dict(row: ContextDelivery) -> dict[str, Any]:
    return {key: getattr(row, key) for key in _VALUE_KEYS if hasattr(row, key)}


async def find_delivery_by_hash(db: AsyncSession, payload_hash: str, at: datetime) -> dict[str, Any] | None:
    """The delivery with this payload that was built closest before `at` (identical payloads are interchangeable)."""
    stmt = (
        select(ContextDelivery).where(ContextDelivery.payload_hash == payload_hash, ContextDelivery.generated_at <= at + BIND_WINDOW_AFTER)
        .order_by(ContextDelivery.generated_at.desc()).limit(1)
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:  # a clock-skewed or later-written delivery: any row with this exact payload still describes it
        row = (await db.execute(
            select(ContextDelivery).where(ContextDelivery.payload_hash == payload_hash).order_by(ContextDelivery.generated_at).limit(1)
        )).scalars().first()
    return _row_dict(row) if row else None


async def find_delivery_in_text(
    db: AsyncSession, surface: str, texts: Iterable[str], at: datetime
) -> tuple[dict[str, Any], int] | None:
    """Bind a delivery that a harness embedded at the start of a longer message (Codex developer text).

    Candidates are the surface's deliveries built just before `at`; one matches when the hash of the text's first
    rendered_chars characters equals its payload_hash. Returns (delivery, rendered_chars) of the closest match.
    """
    candidates = (await db.execute(
        select(ContextDelivery).where(
            ContextDelivery.surface == surface, ContextDelivery.generated_at >= at - BIND_WINDOW_BEFORE,
            ContextDelivery.generated_at <= at + BIND_WINDOW_AFTER,
        ).order_by(ContextDelivery.generated_at.desc())
    )).scalars().all()
    texts = [t for t in texts if t]
    for row in candidates:
        for text in texts:
            if len(text) >= row.rendered_chars > 0 and sha256_text(text[:row.rendered_chars]) == row.payload_hash:
                return _row_dict(row), row.rendered_chars
    return None
