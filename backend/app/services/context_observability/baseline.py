"""Read side of the first-turn capture: medians per (harness, role) and config steps over time.

`baseline` is what DESIGN section 2 measured by hand; `config_steps` is the marker that names a step in a cell's
first-turn size by the config fingerprint that changed with it (Claude: the request shape hash).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import median, median_high
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageSession


@dataclass(frozen=True)
class FirstTurn:
    provider: str
    session_id: str
    agent_id: str
    harness: str
    version: str | None
    role: str | None
    coordinator: bool | None
    launch_mode: str
    model: str | None
    at: datetime
    total: int
    harness_tokens: int | None
    ours_tokens: int | None
    brief_tokens: int | None
    config_fp: str | None
    delivery_id: str | None

    @property
    def cell(self) -> str:
        """Role column of the Cost matrix: launch-table job, launch mode, or unknown."""
        if self.launch_mode == "blank" or self.launch_mode.startswith(("subagent:", "agent:")):
            return self.launch_mode
        return self.role or "unknown"


def _tokens(parts: dict[str, Any], name: str) -> int | None:
    value = (parts.get(name) or {}).get("tokens")
    return int(value) if isinstance(value, (int, float)) else None


async def load_first_turns(
    db: AsyncSession, *, since: datetime, until: datetime | None = None, harness: str | None = None
) -> list[FirstTurn]:
    stmt = select(UsageSession).where(UsageSession.first_turn_tokens.is_not(None), UsageSession.first_turn_at >= since)
    if until is not None:
        stmt = stmt.where(UsageSession.first_turn_at <= until)
    if harness:
        stmt = stmt.where(UsageSession.harness == harness)
    out = []
    for row in (await db.execute(stmt.order_by(UsageSession.first_turn_at))).scalars():
        parts = row.parts or {}
        out.append(FirstTurn(
            provider=row.provider, session_id=row.session_id, agent_id=row.agent_id, harness=row.harness or row.provider,
            version=row.harness_version, role=row.work_role, coordinator=row.coordinator,
            launch_mode=row.launch_mode or "project", model=row.model, at=row.first_turn_at,
            total=int(row.first_turn_tokens or 0), harness_tokens=_tokens(parts, "harness"),
            ours_tokens=_tokens(parts, "ours"), brief_tokens=_tokens(parts, "brief"), config_fp=row.config_fp,
            delivery_id=row.delivery_id,
        ))
    return out


def med(values: Iterable[int | None], *, mean_of_middle: bool = False) -> int | None:
    """Upper median of the known values (None when there are none): the measurement scripts' sorted(v)[n // 2].

    mean_of_middle takes the mean of the middle two for an even count instead (the usual median).
    """
    known = [v for v in values if v is not None]
    if not known:
        return None
    return int(median(known) if mean_of_middle else median_high(known))


def summarize(rows: list[FirstTurn], *, mean_of_middle: bool = False) -> dict[str, int | None]:
    def pick(values: Iterable[int | None]) -> int | None:
        return med(values, mean_of_middle=mean_of_middle)

    return {
        "n": len(rows), "total": pick(r.total for r in rows), "harness": pick(r.harness_tokens for r in rows),
        "ours": pick(r.ours_tokens for r in rows), "brief": pick(r.brief_tokens for r in rows),
    }


def group_by(rows: Iterable[FirstTurn], key: Callable[[FirstTurn], Any]) -> dict[Any, list[FirstTurn]]:
    out: dict[Any, list[FirstTurn]] = defaultdict(list)
    for row in rows:
        out[key(row)].append(row)
    return dict(out)


def config_steps(rows: Iterable[FirstTurn]) -> list[dict[str, Any]]:
    """Config fingerprints of one cell in the order they first appeared, each with the step it made.

    rows: first turns of a single (harness, role, launch_mode) cell. Sessions without a fingerprint are skipped.
    A step names the new fingerprint, when it first appeared, the median before and after and the version change.
    """
    by_fp = group_by((r for r in rows if r.config_fp), lambda r: r.config_fp)
    eras = []
    for fp, items in by_fp.items():
        items.sort(key=lambda r: r.at)
        eras.append({
            "config_fp": fp, "first_at": items[0].at, "last_at": items[-1].at, "n": len(items),
            "median": med(r.total for r in items), "versions": sorted({r.version for r in items if r.version}),
        })
    eras.sort(key=lambda e: e["first_at"])
    steps = []
    for before, after in pairwise(eras):
        steps.append({
            "at": after["first_at"], "config_fp": after["config_fp"], "from_fp": before["config_fp"],
            "median_before": before["median"], "median_after": after["median"],
            "delta": (after["median"] - before["median"]) if after["median"] is not None and before["median"] is not None else None,
            "versions_before": before["versions"], "versions_after": after["versions"],
            "same_version": before["versions"] == after["versions"],
            "n_before": before["n"], "n_after": after["n"],
        })
    return steps
