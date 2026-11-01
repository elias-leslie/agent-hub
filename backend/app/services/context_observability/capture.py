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

from . import extra_capture, first_turn
from .deliveries import (
    BIND_WINDOW_BEFORE,
    Bindings,
    delivery_roots,
    find_delivery_by_hash,
    find_delivery_by_id,
    find_delivery_in_text,
    import_delivery_files,
    load_bindings,
    pick_binding,
    sha256_text,
)

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
    return HeadResult("codex", raw["sid"], "", raw, first_turn.launch_mode_for(path, raw.get("cwd"), None, raw.get("originator")))


async def bind_delivery(db: AsyncSession, head: HeadResult, bindings: Bindings) -> tuple[dict[str, Any] | None, int | None]:
    """The delivery a session started with, and (Codex) how many characters of its developer text it occupies.

    The client's binding file names the exact delivery for the native session or sub-agent id; the payload hash (Claude)
    or the embedded text (Codex) is the fallback only for a session that has no binding file.
    """
    raw = head.raw
    surface = PROVIDER_SURFACE[head.provider]
    bound = pick_binding(bindings, (surface, head.session_id, head.agent_id), raw["first_at"])
    if bound is not None:
        delivery = await find_delivery_by_id(db, *bound)
        ah_chars = None
        if delivery is not None and head.provider == "codex":
            n = int(delivery.get("rendered_chars") or 0)
            if n > 0 and any(len(t) >= n and sha256_text(t[:n]) == delivery["payload_hash"] for t in raw.get("dev_texts") or []):
                ah_chars = n
        return delivery, ah_chars
    if head.provider == "claude":
        for item in raw.get("inst_files") or []:
            if CLAUDE_DELIVERY_MARKER in str(item.get("path")):
                delivery = await find_delivery_by_hash(db, item["sha"], raw["first_at"])
                if delivery:
                    return delivery, None
        return None, None
    found = await find_delivery_in_text(db, surface, raw.get("dev_texts") or [], raw["first_at"])
    return found if found else (None, None)


async def bind_and_compute(db: AsyncSession, head: HeadResult, bindings: Bindings | None = None) -> dict[str, Any]:
    """Column values for one session's first turn (parts, role from the bound delivery, config fingerprint)."""
    raw = head.raw
    delivery, ah_chars = await bind_delivery(db, head, bindings or {})
    parts = first_turn.compute_parts(raw, delivery=delivery, launch_mode=head.launch_mode, ah_chars_in_text=ah_chars)
    return {
        "harness": head.provider, "harness_version": (raw.get("version") or None) and str(raw["version"])[:40],
        "work_role": delivery["work_role"] if delivery else None, "coordinator": delivery["coordinator"] if delivery else None,
        "launch_mode": head.launch_mode[:80], "model": (raw.get("model") or None) and str(raw["model"])[:100],
        "first_turn_tokens": int(raw["total"]), "first_turn_at": raw["first_at"], "parts": parts,
        "delivery_id": delivery["delivery_id"] if delivery else None, "config_fp": raw.get("fp"),
    }


async def load_head_bindings(heads: list[HeadResult]) -> Bindings:
    """Binding files written since just before the earliest of these first turns (none needed without heads)."""
    if not heads:
        return {}
    since = min(h.raw["first_at"] for h in heads) - BIND_WINDOW_BEFORE
    return await asyncio.to_thread(load_bindings, delivery_roots(), since=since)


async def apply_first_turns(db: AsyncSession, heads: Iterable[HeadResult]) -> int:
    """Store first-turn columns on existing usage_sessions rows. Returns rows updated.

    A session whose binding or computation fails is logged and skipped; the others are stored.
    """
    heads = list(heads)
    bindings = await load_head_bindings(heads)
    updated = 0
    for head in heads:
        try:
            async with db.begin_nested():
                values = await bind_and_compute(db, head, bindings)
                result = await db.execute(
                    update(UsageSession).where(
                        UsageSession.provider == head.provider, UsageSession.session_id == head.session_id[:100],
                        UsageSession.agent_id == head.agent_id[:100],
                    ).values(**values)
                )
        except Exception as exc:
            logger.warning("first turn not stored for %s/%s: %s: %s", head.provider, head.session_id, type(exc).__name__, (str(exc).splitlines() or [""])[0][:200])
            continue
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
        except Exception as exc:  # one odd transcript must not stop the rest
            logger.warning("first turn unreadable %s: %s: %s", path, type(exc).__name__, (str(exc).splitlines() or [""])[0][:200])
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
    extra = await extra_capture.backfill_extra(db, since=since, until=until, now=now)
    return {
        "deliveries_imported": imported, "sessions_read": len(heads), "sessions_updated": updated,
        "sessions_skipped": len(heads) - updated, **extra, "seconds": int(time.monotonic() - started),
    }
