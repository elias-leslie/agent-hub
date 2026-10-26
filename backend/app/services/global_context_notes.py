"""One note for each change to context that every agent receives.

Global prompts (the Safety Directive among them) and global-scope mandate
memories reach every agent. Agents edit them legitimately, about daily, so a
change is neither an ask nor an owner notification (owner decision 2026-10-26: no
unactionable pushes): it is one log line naming the calling client, with the
diff (the revision history keeps the full change), including any change to who receives it, when, or in what form
(targeting, triggers, workflows, render mode). Excluding one of them from a
consumer profile through a runtime-context placement drops it just as surely,
so a new exclusion sends a note too. Notes
go out after the transaction commits; a rolled-back change sends nothing.
Sending never fails the write.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.memory_unified import Memory
from app.models.prompt import Prompt

logger = logging.getLogger(__name__)

_PENDING = "global_context_notes"
_DIFF_LIMIT = 3000
_VERBS = {"create": "added", "delete": "deleted", "restore": "restored", "exclude": "excluded"}
_ALWAYS_SENT = {"create", "delete", "exclude"}
GLOBAL_PROMPT_TYPES = ("global_guardrail", "global_mandate")
_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class GlobalContextNote:
    kind: str  # "Global prompt" or "Global mandate memory"
    name: str
    action: str
    changed_by: str | None
    before: str | None
    after: str | None
    reason: str | None = None
    flags: tuple[str, ...] = ()
    excluded_from: str | None = None  # for action "exclude": the profile and project layer

    @property
    def title(self) -> str:
        return f"{self.kind} {_VERBS.get(self.action, 'edited')}"

    @property
    def key(self) -> str:
        return f"agent-hub.global-context.{self.kind.split()[-1].lower()}.{self.name}"

    def message(self) -> str:
        actor = self.changed_by or "an unidentified caller"
        if self.action == "exclude":
            lines = [f"{self.name} was excluded from {self.excluded_from} by {actor}. "
                     "Those agents no longer receive it."]
        else:
            lines = [f"{self.name} was {_VERBS.get(self.action, 'edited')} by {actor}. Every agent receives it."]
        lines += list(self.flags)
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        diff = "\n".join(difflib.unified_diff(
            (self.before or "").splitlines(), (self.after or "").splitlines(), "before", "after", lineterm="", n=1,
        ))
        if diff:
            if len(diff) > _DIFF_LIMIT:
                diff = diff[:_DIFF_LIMIT] + "\n(diff cut short; the full change is in the revision history)"
            lines += ["", diff]
        return "\n".join(lines)


def queue_global_context_note(db: AsyncSession, note: GlobalContextNote) -> None:
    """Send ``note`` once this session's transaction commits (skipped when nothing agents see changed)."""
    if note.action not in _ALWAYS_SENT and note.before == note.after and not note.flags:
        return
    db.sync_session.info.setdefault(_PENDING, []).append(note)


@event.listens_for(Session, "after_commit")
def _send_after_commit(session: Session) -> None:
    notes = session.info.pop(_PENDING, None)
    if not notes:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No event loop; %d global context note(s) not sent", len(notes))
        return
    for note in notes:
        task = loop.create_task(send_note(note))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


@event.listens_for(Session, "after_soft_rollback")
def _drop_after_rollback(session: Session, previous_transaction: object) -> None:
    session.info.pop(_PENDING, None)


async def send_note(note: GlobalContextNote) -> None:
    logger.info("%s: %s", note.title, note.message())


def flag_changes(before: dict[str, object] | None, after: dict[str, object]) -> tuple[str, ...]:
    """Readable lines for changed switches, e.g. ``enabled: True -> False``."""
    if before is None:
        return ()
    return tuple(f"{key}: {before.get(key)} -> {value}" for key, value in after.items() if before.get(key) != value)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _excluded(placements: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {(str(p["source_type"]), str(p["source_id"])) for p in placements
            if p.get("enabled", True) and p.get("mode") == "exclude"}


async def queue_exclusion_notes(
    db: AsyncSession,
    *,
    consumer_profile: str,
    project_id: str | None,
    before: Iterable[Mapping[str, Any]],
    after: Iterable[Mapping[str, Any]],
    changed_by: str | None,
) -> None:
    """Note each global prompt or global mandate memory newly excluded at this placement layer."""
    added = _excluded(after) - _excluded(before)
    if not added:
        return
    where = f"{consumer_profile} context in " + (f"project {project_id}" if project_id else "every project")
    slugs = sorted(source_id for source_type, source_id in added if source_type == "prompt")
    memory_ids = [memory_id for source_type, source_id in added
                  if source_type == "memory" and (memory_id := _uuid(source_id)) is not None]
    notes: list[GlobalContextNote] = []
    if slugs:
        prompts = (await db.execute(select(Prompt).where(
            Prompt.slug.in_(slugs),
            Prompt.is_global.is_(True) | Prompt.prompt_type.in_(GLOBAL_PROMPT_TYPES),
        ).order_by(Prompt.slug))).scalars()
        notes += [GlobalContextNote(kind="Global prompt", name=p.slug, action="exclude", changed_by=changed_by,
                                    before=None, after=None, excluded_from=where) for p in prompts]
    if memory_ids:
        memories = (await db.execute(select(Memory).where(
            Memory.id.in_(memory_ids), Memory.scope == "global", Memory.tier == 1,
        ).order_by(Memory.id))).scalars()
        notes += [GlobalContextNote(kind="Global mandate memory", name=f"{m.summary or m.name} ({str(m.id)[:8]})",
                                    action="exclude", changed_by=changed_by, before=None, after=None,
                                    excluded_from=where) for m in memories]
    for note in notes:
        queue_global_context_note(db, note)
