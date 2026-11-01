"""Who wrote a memory or prompt revision: the stored writer, resolved through its context delivery.

Revisions store the raw writer (``writer_kind``, the agent's context delivery hash
and its Aico session; see ``app.core.request_actor``). Harness, work role and
project come from the matching ``context_deliveries`` row when reading, so a
revision written before that row exists (or before the table exists) still
resolves once it does. Unmatched writers keep their raw session and delivery.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from pydantic import BaseModel
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

# context_deliveries (models/context_observability.py) column per resolved field. Read with plain SQL
# guarded by to_regclass so this works before that table is migrated in.
_FIELD_COLUMNS = {"harness": "surface", "work_role": "work_role", "project": "project_id", "coordinator": "coordinator"}
_KEY_COLUMNS = {"hash": "payload_hash", "session": "session_id"}


class RevisionWriter(BaseModel):
    """The writer of one revision; unknown parts stay None (never guessed)."""

    kind: str | None = None  # owner | agent | client | system; None on rows written before writer capture
    session: str | None = None
    delivery: str | None = None
    harness: str | None = None
    work_role: str | None = None
    project: str | None = None
    coordinator: bool | None = None
    resolved: bool = False  # True when a context delivery matched


class _HasWriter(Protocol):
    writer_kind: str | None
    writer_delivery: str | None
    writer_session: str | None


async def _deliveries_table_exists(db: AsyncSession) -> bool:
    return bool((await db.execute(text("SELECT to_regclass('context_deliveries') IS NOT NULL"))).scalar())


async def _latest_by(
    db: AsyncSession, keys: tuple[str, ...], values: dict[str, set[str]]
) -> dict[tuple[str, ...], dict[str, Any]]:
    """The newest delivery row per key tuple (hash, session, or both)."""
    if not all(values.get(key) for key in keys):
        return {}
    columns = [_KEY_COLUMNS[key] for key in keys]
    selected = ", ".join(
        [f'{column} AS "k{i}"' for i, column in enumerate(columns)]
        + [f'{column} AS "{field}"' for field, column in _FIELD_COLUMNS.items()]
    )
    where = " AND ".join(f"{column} IN :v{i}" for i, column in enumerate(columns))
    statement = text(
        f"SELECT DISTINCT ON ({', '.join(columns)}) {selected} FROM context_deliveries "
        f"WHERE {where} ORDER BY {', '.join(columns)}, generated_at DESC"
    ).bindparams(*(bindparam(f"v{i}", expanding=True) for i in range(len(keys))))
    params = {f"v{i}": sorted(values[key]) for i, key in enumerate(keys)}
    rows = (await db.execute(statement, params)).mappings().all()
    return {tuple(str(row[f"k{i}"]) for i in range(len(keys))): dict(row) for row in rows}


async def resolve_writers(db: AsyncSession, revisions: Iterable[_HasWriter]) -> list[RevisionWriter]:
    """One ``RevisionWriter`` per revision, in order.

    A payload hash names the delivered text, which identical sessions share, so the
    match prefers (hash, session), then the session's latest delivery, then the hash.
    """
    writers = [
        RevisionWriter(kind=r.writer_kind, session=r.writer_session, delivery=r.writer_delivery) for r in revisions
    ]
    values = {"hash": {w.delivery for w in writers if w.delivery}, "session": {w.session for w in writers if w.session}}
    if not (values["hash"] or values["session"]):
        return writers
    if not await _deliveries_table_exists(db):
        return writers
    by_pair = await _latest_by(db, ("hash", "session"), values)
    by_session = await _latest_by(db, ("session",), values)
    by_hash = await _latest_by(db, ("hash",), values)
    for writer in writers:
        delivery, session = writer.delivery or "", writer.session or ""
        match = by_pair.get((delivery, session)) or by_session.get((session,)) or by_hash.get((delivery,))
        if match is None:
            continue
        writer.harness = match.get("harness")
        writer.work_role = match.get("work_role")
        writer.project = match.get("project")
        coordinator = match.get("coordinator")
        writer.coordinator = None if coordinator is None else bool(coordinator)
        writer.resolved = True
    return writers
