"""One Nightshift note for each change to context that every agent receives.

Global prompts (the Safety Directive among them) and global-scope mandate
memories reach every agent. Agents edit them legitimately, about daily, so a
change is not an ask: it is one info note naming the calling client, with the
diff. Notes go out after the transaction commits; a rolled-back change sends
nothing. Sending never fails the write.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import shutil
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)

_PENDING = "global_context_notes"
_DIFF_LIMIT = 3000
_SEND_TIMEOUT_S = 30.0
_VERBS = {"create": "added", "delete": "deleted", "restore": "restored"}
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

    @property
    def title(self) -> str:
        return f"{self.kind} {_VERBS.get(self.action, 'edited')}"

    @property
    def key(self) -> str:
        return f"agent-hub.global-context.{self.kind.split()[-1].lower()}.{self.name}"

    def message(self) -> str:
        lines = [f"{self.name} was {_VERBS.get(self.action, 'edited')} by {self.changed_by or 'an unidentified caller'}. "
                 "Every agent receives it."]
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
    if note.action not in {"create", "delete"} and note.before == note.after and not note.flags:
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
    binary = shutil.which("nightshift")
    if binary is None:
        logger.warning("nightshift not found; global context note for %s not sent", note.name)
        return
    try:
        process = await create_process(
            binary, "push", "--severity", "info", "--title", note.title,
            "--key", note.key, "--cooldown", "0", note.message(),
            stdout=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        logger.warning("Global context note for %s failed: %s", note.name, exc)
        return
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=_SEND_TIMEOUT_S)
    except TimeoutError:
        process.kill()
        logger.warning("Global context note for %s timed out", note.name)
        return
    if process.returncode:
        logger.warning("Global context note for %s failed (%s): %s", note.name, process.returncode,
                       (stderr or b"").decode(errors="replace")[:300])


def flag_changes(before: dict[str, object] | None, after: dict[str, object]) -> tuple[str, ...]:
    """Readable lines for changed switches, e.g. ``enabled: True -> False``."""
    if before is None:
        return ()
    return tuple(f"{key}: {before.get(key)} -> {value}" for key, value in after.items() if before.get(key) != value)
