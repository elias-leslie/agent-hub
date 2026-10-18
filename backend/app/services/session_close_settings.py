"""Session close settings: the thresholds that decide when a quiet session is closed.

Live classification (``_session_lifecycle``) runs synchronously for every session it
renders, so it reads an in-process copy. The API process loads it at startup and
replaces it on every update; worker tasks reload it before they reap.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import SessionCloseSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionCloseThresholds:
    dead_candidate_after_minutes: int = 30
    reapable_after_minutes: int = 360
    zero_event_close_after_minutes: int = 60
    transcript_sync_close_after_minutes: int = 60
    completion_close_after_minutes: int = 240
    any_session_close_after_minutes: int = 1440
    codex_close_inactive_enabled: bool = True
    codex_scan_hours: int = 24
    updated_by: str | None = None

    @property
    def dead_candidate_after_seconds(self) -> int:
        return self.dead_candidate_after_minutes * 60

    @property
    def reapable_after_seconds(self) -> int:
        return self.reapable_after_minutes * 60

    @property
    def zero_event_close_after_seconds(self) -> int:
        return self.zero_event_close_after_minutes * 60

    @property
    def transcript_sync_close_after_seconds(self) -> int:
        return self.transcript_sync_close_after_minutes * 60

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


SETTING_FIELDS = tuple(f.name for f in fields(SessionCloseThresholds) if f.name != "updated_by")
_current = SessionCloseThresholds()


def current() -> SessionCloseThresholds:
    """The thresholds this process last loaded (defaults until the first load)."""
    return _current


def _from_row(row: SessionCloseSettings | None) -> SessionCloseThresholds:
    if row is None:
        return SessionCloseThresholds()
    return SessionCloseThresholds(
        **{name: getattr(row, name) for name in SETTING_FIELDS}, updated_by=row.updated_by
    )


async def _load_with(db: AsyncSession) -> SessionCloseThresholds:
    global _current
    row = (
        await db.execute(select(SessionCloseSettings).where(SessionCloseSettings.id == 1))
    ).scalar_one_or_none()
    _current = _from_row(row)
    return _current


async def load(db: AsyncSession | None = None) -> SessionCloseThresholds:
    """Read the stored settings into this process; keep the last copy if the DB is unreachable."""
    try:
        if db is not None:
            return await _load_with(db)
        async with async_session() as session:
            return await _load_with(session)
    except Exception as exc:  # classification must keep working without the DB
        logger.warning("Session close settings unavailable, keeping last values: %s", exc)
        return _current


def validate(values: SessionCloseThresholds) -> None:
    """Refuse combinations that would close sessions before they can look dead."""
    if values.reapable_after_minutes < values.dead_candidate_after_minutes:
        raise ValueError("Close after quiet must be at least as long as Looks dead after.")
    if values.any_session_close_after_minutes < values.completion_close_after_minutes:
        raise ValueError("Close any session must be at least as long as Close completions.")


async def update(db: AsyncSession, changes: dict[str, object], *, updated_by: str) -> SessionCloseThresholds:
    """Apply the given fields, validate the result, store it and refresh this process."""
    global _current
    unknown = set(changes) - set(SETTING_FIELDS)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    row = (
        await db.execute(
            select(SessionCloseSettings).where(SessionCloseSettings.id == 1).with_for_update()
        )
    ).scalar_one_or_none()
    base = _from_row(row)
    merged = replace(base, **changes, updated_by=updated_by)
    validate(merged)
    if row is None:
        row = SessionCloseSettings(id=1)
        db.add(row)
    for name in SETTING_FIELDS:
        setattr(row, name, getattr(merged, name))
    row.updated_by = updated_by
    await db.commit()
    _current = merged
    return merged
