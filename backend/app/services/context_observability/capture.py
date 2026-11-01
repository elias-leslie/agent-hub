"""Write measured first turns onto usage_sessions, and the one-time 30-day backfill.

The collector calls `apply_first_turns` with the raw heads it read for sessions that appeared in a pass. The backfill
walks the same transcripts' heads (not their bodies) and applies them the same way, so live capture and history agree.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageSession
from app.utils.native_homes import claude_project_roots, codex_session_roots

from . import first_turn
from .deliveries import find_delivery_by_hash, find_delivery_in_text, import_delivery_files

logger = logging.getLogger(__name__)

BACKFILL_DAYS = 30
CLAUDE_DELIVERY_MARKER = "context-deliveries"
PROVIDER_SURFACE = {"claude": "claude_code", "codex": "codex"}


@dataclass
class HeadResult:
    """One session's raw first turn, ready to bind and store."""

    provider: str
    session_id: str
    agent_id: str
    raw: dict[str, Any]
    launch_mode: str


def head_for_claude(path: Path) -> HeadResult | None:
    raw = first_turn.read_claude_head(path)
    if raw is None:
        return None
    sid, aid = first_turn.claude_identity(path)
    mode = first_turn.launch_mode_for(path, raw.get("cwd"), first_turn.claude_agent_type(path))
    return HeadResult("claude", sid, aid, raw, mode)


def head_for_codex(path: Path) -> HeadResult | None:
    """Root sessions only: a child thread's first request carries inherited history, so it has no first turn of its own."""
    raw = first_turn.read_codex_head(path)
    if raw is None or raw.get("aid") or not raw.get("sid"):
        return None
    return HeadResult("codex", raw["sid"], "", raw, first_turn.launch_mode_for(path, raw.get("cwd"), None))


async def bind_and_compute(db: AsyncSession, head: HeadResult) -> dict[str, Any]:
    """Column values for one session's first turn (parts, role from the bound delivery, config fingerprint)."""
    raw = head.raw
    delivery: dict[str, Any] | None = None
    ah_chars: int | None = None
    if head.provider == "claude":
        for item in raw.get("inst_files") or []:
            if CLAUDE_DELIVERY_MARKER in str(item.get("path")):
                delivery = await find_delivery_by_hash(db, item["sha"], raw["first_at"])
                if delivery:
                    break
    else:
        found = await find_delivery_in_text(db, PROVIDER_SURFACE["codex"], raw.get("dev_texts") or [], raw["first_at"])
        if found:
            delivery, ah_chars = found
    parts = first_turn.compute_parts(raw, delivery=delivery, launch_mode=head.launch_mode, ah_chars_in_text=ah_chars)
    return {
        "harness": head.provider, "harness_version": (raw.get("version") or None) and str(raw["version"])[:40],
        "work_role": delivery["work_role"] if delivery else None, "coordinator": delivery["coordinator"] if delivery else None,
        "launch_mode": head.launch_mode[:80], "model": (raw.get("model") or None) and str(raw["model"])[:100],
        "first_turn_tokens": int(raw["total"]), "first_turn_at": raw["first_at"], "parts": parts,
        "delivery_id": delivery["delivery_id"] if delivery else None, "config_fp": raw.get("fp"),
    }


async def apply_first_turns(db: AsyncSession, heads: Iterable[HeadResult]) -> int:
    """Store first-turn columns on existing usage_sessions rows. Returns rows updated."""
    updated = 0
    for head in heads:
        values = await bind_and_compute(db, head)
        result = await db.execute(
            update(UsageSession).where(
                UsageSession.provider == head.provider, UsageSession.session_id == head.session_id[:100],
                UsageSession.agent_id == head.agent_id[:100],
            ).values(**values)
        )
        updated += cast(CursorResult[Any], result).rowcount or 0
    return updated


def _heads_since(since: float, until: datetime | None) -> list[HeadResult]:
    """Read the heads of every transcript touched since `since` whose first turn falls before `until` (blocking)."""
    out: list[HeadResult] = []
    files: list[tuple[Path, Any]] = []
    for root in codex_session_roots():
        files += [(p, head_for_codex) for p in _recent(root, "*/*/*/*.jsonl", since)]
    for root in claude_project_roots():
        files += [(p, head_for_claude) for p in _recent(root, "**/*.jsonl", since)]
    for path, reader in files:
        try:
            head = reader(path)
        except OSError:
            continue
        if head is not None and (until is None or head.raw["first_at"] <= until):
            out.append(head)
    return out


def _recent(root: Path, pattern: str, since: float) -> list[Path]:
    if not root.is_dir():
        return []
    found = []
    for path in root.glob(pattern):
        try:
            if path.stat().st_mtime >= since:
                found.append(path)
        except OSError:
            continue
    return sorted(found)


async def backfill(
    db: AsyncSession, *, days: int = BACKFILL_DAYS, until: datetime | None = None, now: datetime | None = None,
) -> dict[str, int]:
    """Import delivery contract files and measure the first turn of every session in the last `days`.

    Session rows must already exist (the ledger pass creates them); a transcript without one is counted as skipped.
    Idempotent: a rerun recomputes the same values.
    """
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    started = time.monotonic()
    imported = await import_delivery_files(db, since=since - timedelta(days=1))
    await db.flush()
    heads = await asyncio.to_thread(_heads_since, since.timestamp(), until)
    heads = [h for h in heads if h.raw["first_at"] >= since]
    updated = await apply_first_turns(db, heads)
    return {
        "deliveries_imported": imported, "sessions_read": len(heads), "sessions_updated": updated,
        "sessions_skipped": len(heads) - updated, "seconds": int(time.monotonic() - started),
    }
