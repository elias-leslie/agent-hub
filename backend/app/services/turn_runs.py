"""Server-owned chat turns.

A streaming turn runs as a task owned by this registry, not by the HTTP request that started it. Every SSE
chunk it produces goes into an in-memory log; the starting request and any later ``GET /sessions/{id}/stream``
are just subscribers reading that log, so they all see identical bytes and a dropped connection costs nothing.

Why in-process rather than the Hatchet worker or Redis: the provider stream, the tool loop and the
cancel event already live in this process, and a worker would add a queue hop before the first token plus a
relay back to the API for every event. The turn dies with the process either way, so a log that outlives it
(Redis) would only describe a turn nobody can resume. What happens on restart is made explicit instead: the
turn's state is persisted as running when it starts and as its final state when it ends; shutdown and the
startup sweep turn anything left running into ``interrupted`` with an ``error`` event the next reattach
returns. Nothing is stopped on a timer; a turn ends on its terminal event, an explicit cancel, or the death
of this process.

The log is bounded by the turn's life: kept whole while it runs (capped in bytes, oldest first, see
``turn_log_max_bytes``), and for the newest ``turn_log_retained_finished`` finished turns after it ends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

TURN_KEY = "durable_turn"  # session.provider_metadata[TURN_KEY]: {turn_id, state, started_at, ended_at, ...}
DONE_CHUNK = "data: [DONE]\n\n"
HEARTBEAT_CHUNK = ": heartbeat\n\n"
INTERRUPTED_MESSAGE = "Turn interrupted: the backend stopped while it was running"

_TERMINAL_STATE = {"done": "completed", "error": "error", "cancel_acknowledged": "cancelled"}
_PHASE_BY_EVENT = {
    "connected": "waiting_for_model",
    "thinking": "thinking",
    "content": "responding",
    "tool_use": "running_tool",
    "tool_start": "running_tool",
    "tool_result": "waiting_for_model",
    "turn_retry": "retrying",
}


class TurnLogGap(Exception):
    """The requested replay point is older than the oldest event still kept."""

    def __init__(self, after_seq: int, oldest_seq: int) -> None:
        super().__init__(f"events up to seq {oldest_seq - 1} are no longer kept (asked after {after_seq})")
        self.after_seq = after_seq
        self.oldest_seq = oldest_seq


class TurnRunning(Exception):
    """A turn is already running for the session."""

    def __init__(self, run: TurnRun) -> None:
        super().__init__(f"session {run.session_id} already has a running turn")
        self.run = run


@dataclass(frozen=True, slots=True)
class LoggedEvent:
    seq: int
    type: str
    chunk: str


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def sse_event(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


class TurnRun:
    """One turn: its task, state and event log."""

    def __init__(self, session_id: str, turn_id: str, *, max_bytes: int, persist: bool = True) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.persist = persist
        self.started_at = now_iso()
        self.ended_at: str | None = None
        self.state = "running"  # running | completed | error | cancelled | interrupted
        self.phase = "waiting_for_model"
        self.tool_name: str | None = None
        self.cancel_requested = False
        self.interrupted = False
        self.finished = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self._max_bytes = max_bytes
        self._events: list[LoggedEvent] = []
        self._seqs: list[int] = []
        self._bytes = 0
        self._oldest_kept = 1  # seq of the first event the log still holds
        self._cond = asyncio.Condition()
        self._terminal: str | None = None

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def last_seq(self) -> int:
        return self._seqs[-1] if self._seqs else 0

    # -- writing ---------------------------------------------------------------------------------------

    def _record(self, chunk: str) -> LoggedEvent | None:
        """Parse one ``data: {json}`` chunk into the log. Comments and the end marker are not events."""
        if not chunk.startswith("data: {") or self._terminal is not None:
            # Nothing follows a turn's terminal event (done, error, cancel): a late chunk is never published.
            return None
        try:
            payload = json.loads(chunk[6:])
        except ValueError:
            return None
        seq, kind = payload.get("seq"), payload.get("type")
        if not isinstance(seq, int) or not isinstance(kind, str) or seq <= self.last_seq:
            return None
        event = LoggedEvent(seq, kind, chunk)
        self._events.append(event)
        self._seqs.append(seq)
        self._bytes += len(chunk)
        while self._bytes > self._max_bytes and len(self._events) > 1:
            dropped = self._events.pop(0)
            self._seqs.pop(0)
            self._bytes -= len(dropped.chunk)
            self._oldest_kept = self._seqs[0]
        if kind in _TERMINAL_STATE:
            self._terminal = kind
        elif kind in _PHASE_BY_EVENT:
            self.phase = _PHASE_BY_EVENT[kind]
            self.tool_name = payload.get("tool_name") if self.phase == "running_tool" else None
        return event

    async def _publish(self, chunk: str) -> None:
        if self._record(chunk) is not None:
            async with self._cond:
                self._cond.notify_all()

    async def _finish(self, state: str) -> None:
        self.state = state
        self.ended_at = now_iso()
        self.phase = "idle"
        self.tool_name = None
        self.finished.set()
        async with self._cond:
            self._cond.notify_all()

    # -- reading ---------------------------------------------------------------------------------------

    def events_after(self, after_seq: int) -> list[LoggedEvent]:
        if after_seq + 1 < self._oldest_kept:
            raise TurnLogGap(after_seq, self._oldest_kept)
        return self._events[bisect_right(self._seqs, after_seq) :]

    async def follow(self, after_seq: int = 0, heartbeat_seconds: float | None = None) -> AsyncGenerator[str]:
        """Replay events with ``seq > after_seq``, then follow live until the turn ends; closes with ``[DONE]``.

        Raises :class:`TurnLogGap` before yielding anything when the replay point has been dropped.
        """
        interval = heartbeat_seconds or settings.stream_heartbeat_seconds
        cursor = after_seq
        pending = self.events_after(cursor)
        while True:
            for event in pending:
                yield event.chunk
                cursor = event.seq
            if self.finished.is_set() and cursor >= self.last_seq:
                break
            async with self._cond:
                if not (self.finished.is_set() or self.last_seq > cursor):
                    try:
                        await asyncio.wait_for(self._cond.wait(), interval)
                    except TimeoutError:
                        pending = []  # already delivered: a heartbeat must not replay them
                        yield HEARTBEAT_CHUNK
                        continue
            pending = self.events_after(cursor)
        yield DONE_CHUNK

    # -- control ---------------------------------------------------------------------------------------

    def interrupt(self) -> None:
        """Stop the turn because this process is going away; it ends as ``interrupted``."""
        self.interrupted = True
        if self.task is not None and not self.task.done():
            self.task.cancel()

    async def _drive(self, source: AsyncIterator[str]) -> None:
        try:
            try:
                await _persist_turn(self, "running")
                async for chunk in source:
                    if self.interrupted:
                        break
                    await self._publish(chunk)
            except asyncio.CancelledError:
                if not self.interrupted:
                    raise
                if (task := asyncio.current_task()) is not None:
                    task.uncancel()  # shutdown stops the turn; the bookkeeping below still has to run
            except Exception as exc:  # the stream converts its own failures; this is the last line
                logger.exception("Turn %s for session %s failed outside the stream", self.turn_id, self.session_id)
                await self._publish(self._error_chunk(f"Turn failed: {exc}"))
            finally:
                aclose = getattr(source, "aclose", None)
                if aclose is not None:
                    with suppress(Exception, asyncio.CancelledError):
                        await aclose()
            ended_by_stream = self._terminal is not None
            if not ended_by_stream:
                if self.interrupted:
                    await self._publish(self._error_chunk(INTERRUPTED_MESSAGE, code="turn_interrupted"))
                else:
                    await self._publish(self._error_chunk("The turn ended without a result"))
            state = "interrupted" if self.interrupted and not ended_by_stream else _TERMINAL_STATE[self._terminal or "error"]
            await _persist_turn(self, state)
            await self._finish(state)
        except asyncio.CancelledError:
            await self._finish("interrupted")
            raise
        except Exception:
            logger.exception("Turn %s bookkeeping failed for session %s", self.turn_id, self.session_id)
            if not self.finished.is_set():
                await self._finish("error")

    def _error_chunk(self, message: str, *, code: str | None = None) -> str:
        payload: dict[str, Any] = {
            "type": "error",
            "seq": self.last_seq + 1,
            "error": message,
            "session_id": self.session_id,
        }
        if code:
            payload["code"] = code
        return sse_event(payload)


class TurnRegistry:
    """The turns of this process, newest per session; finished ones are evicted oldest first."""

    def __init__(self) -> None:
        self._runs: OrderedDict[str, TurnRun] = OrderedDict()

    def get(self, session_id: str) -> TurnRun | None:
        return self._runs.get(session_id)

    def running(self, session_id: str) -> TurnRun | None:
        run = self._runs.get(session_id)
        return run if run is not None and run.running else None

    def running_runs(self) -> list[TurnRun]:
        return [run for run in self._runs.values() if run.running]

    def start(
        self, session_id: str, source: AsyncIterator[str], *, turn_id: str | None = None, persist: bool = True
    ) -> TurnRun:
        """Run ``source`` (SSE chunks) as the session's turn. Raises :class:`TurnRunning` if one is running.

        ``persist=False`` keeps the turn's state off the session row (callers running without a database).
        """
        if (live := self.running(session_id)) is not None:
            raise TurnRunning(live)
        run = TurnRun(
            session_id, turn_id or str(uuid.uuid4()), max_bytes=settings.turn_log_max_bytes, persist=persist
        )
        self._runs.pop(session_id, None)
        self._runs[session_id] = run
        run.task = asyncio.create_task(run._drive(source), name=f"turn:{session_id}")
        run.task.add_done_callback(lambda _task: self._evict())
        return run

    def _evict(self) -> None:
        finished = [sid for sid, run in self._runs.items() if not run.running]
        for sid in finished[: max(len(finished) - settings.turn_log_retained_finished, 0)]:
            del self._runs[sid]

    def note_cancel_requested(self, session_id: str) -> None:
        if (run := self.running(session_id)) is not None:
            run.cancel_requested = True

    async def shutdown(self) -> None:
        """This process is stopping: end every running turn as interrupted, visibly and persisted."""
        runs = self.running_runs()
        for run in runs:
            run.interrupt()
        tasks = [run.task for run in runs if run.task is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


registry = TurnRegistry()


def turn_state_for(session_id: str) -> tuple[str, str | None]:
    """(``running`` | ``idle``, phase) for the session as this process knows it."""
    run = registry.running(session_id)
    if run is None:
        return "idle", None
    return "running", f"{run.phase}:{run.tool_name}" if run.tool_name else run.phase


# -- persisted state -------------------------------------------------------------------------------------


def _with_turn_state(session: Any, **fields: Any) -> None:
    metadata = dict(session.provider_metadata) if isinstance(session.provider_metadata, dict) else {}
    current = metadata.get(TURN_KEY)
    metadata[TURN_KEY] = {**(current if isinstance(current, dict) else {}), **fields}
    session.provider_metadata = metadata


async def _persist_turn(run: TurnRun, state: str) -> None:
    """Record the turn's state on its session; the startup sweep reads ``running`` as left behind by a dead process."""
    from app.db import async_session
    from app.models import Session

    if not run.persist:
        return
    try:
        async with async_session() as db:
            session = await db.get(Session, run.session_id)
            if session is None:
                return
            fields: dict[str, Any] = {"turn_id": run.turn_id, "state": state, "started_at": run.started_at}
            if state != "running":
                fields.update(ended_at=run.ended_at or now_iso(), last_seq=run.last_seq)
            _with_turn_state(session, **fields)
            if state == "interrupted":
                await _record_interruption(db, session)
            await db.commit()
    except Exception as exc:
        logger.warning("Could not persist turn state %s for %s: %s", state, run.session_id, exc)


async def _record_interruption(db: Any, session: Any) -> None:
    from app.services.event_storage import store_error_event
    from app.services.session_live_activity import mark_session_terminal_state

    mark_session_terminal_state(
        session,
        phase="interrupted",
        status="error",
        summary=INTERRUPTED_MESSAGE,
        termination_reason="turn_interrupted",
    )
    await store_error_event(db, session.id, "turn_interrupted", INTERRUPTED_MESSAGE, agent_id=session.agent_slug)


async def interrupt_orphaned_turns() -> int:
    """At startup: a turn persisted as running belongs to a process that no longer exists. End it as interrupted."""
    from sqlalchemy import select

    from app.db import async_session
    from app.models import Session

    count = 0
    async with async_session() as db:
        running = Session.provider_metadata[TURN_KEY]["state"].as_string() == "running"
        for session in (await db.execute(select(Session).where(running))).scalars().all():
            _with_turn_state(session, state="interrupted", ended_at=now_iso())
            await _record_interruption(db, session)
            count += 1
        await db.commit()
    return count


def interrupted_error_event(session_id: str, seq: int) -> str:
    """The ``error`` event a reattach returns for a turn that was interrupted."""
    return sse_event(
        {
            "type": "error",
            "seq": seq,
            "error": INTERRUPTED_MESSAGE,
            "code": "turn_interrupted",
            "session_id": session_id,
        }
    )
