"""Markers: the things that can move a cell's context, in time order.

Most come from the `context_markers` SQL view: revisions of delivered memories and prompts, the first sighting of each
harness version, config fingerprint changes and placement changes. Our config files (context_knobs rows, for example
Tether's lane-tools.json) are not in the database, so their changes are read from git history on demand.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.safe_subprocess import create_process

from .policy import Knob

logger = logging.getLogger(__name__)

GIT_TIMEOUT_S = 20


@dataclass(frozen=True)
class Marker:
    at: datetime
    kind: str  # memory | prompt | harness_version | config | placement | knob
    harness: str | None
    role: str | None  # usage_sessions.work_role the marker was seen on (config only)
    launch_mode: str | None
    ref: str
    label: str
    detail: dict[str, Any] = field(default_factory=dict)


async def view_markers(
    db: AsyncSession, start: datetime, end: datetime, *, harness: str | None = None, kinds: tuple[str, ...] | None = None,
) -> list[Marker]:
    """Markers from the view with start <= at <= end. harness filters the harness-bound kinds; memory, prompt and
    placement markers have no harness and always stay."""
    rows = (await db.execute(text(
        "SELECT at, kind, harness, work_role, launch_mode, ref, label, detail FROM context_markers"
        " WHERE at >= :start AND at <= :end AND (CAST(:harness AS text) IS NULL OR harness IS NULL OR harness = :harness)"
        " AND (CAST(:kinds AS text[]) IS NULL OR kind = ANY(CAST(:kinds AS text[]))) ORDER BY at"
    ), {"start": start, "end": end, "harness": harness, "kinds": list(kinds) if kinds else None})).all()
    return [Marker(at=r.at, kind=r.kind, harness=r.harness, role=r.work_role, launch_mode=r.launch_mode, ref=str(r.ref),
                   label=str(r.label), detail=dict(r.detail or {})) for r in rows]


async def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = await create_process("git", "-C", str(repo), *args)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=GIT_TIMEOUT_S)
    except (OSError, TimeoutError):
        logger.warning("git %s in %s did not run", args[0], repo, exc_info=True)
        return None
    if proc.returncode != 0:
        logger.warning("git %s in %s exited %s: %s", args[0], repo, proc.returncode, err.decode(errors="replace").strip()[:200])
        return None
    return out.decode(errors="replace")


async def knob_markers(knobs: list[Knob], start: datetime, end: datetime) -> list[Marker]:
    """Commits that changed a knob's file between start and end (a git checkout that is missing yields none)."""
    out: list[Marker] = []
    for knob in knobs:
        repo = Path(knob.repo_path)
        if not repo.is_dir():
            continue
        log = await _git(repo, "log", f"--since={start.isoformat()}", f"--until={end.isoformat()}",
                         "--format=%H%x09%aI%x09%s", "--", knob.file_path)
        for line in (log or "").splitlines():
            sha, _, rest = line.partition("\t")
            when, _, subject = rest.partition("\t")
            try:
                at = datetime.fromisoformat(when).astimezone(UTC)
            except ValueError:
                continue
            out.append(Marker(at=at, kind="knob", harness=knob.harness if knob.harness != "*" else None, role=None,
                              launch_mode=None, ref=sha[:8], label=knob.name,
                              detail={"commit": sha[:8], "subject": subject[:200], "file": knob.file_path}))
    out.sort(key=lambda m: m.at)
    return out
