"""What a running attempt is doing right now: a phase and when its harness last said anything.

Executors fold every event their harness emits into the attempt's ``LiveStatus`` with ``note_live`` (a plain in-memory
assignment, so token deltas cost nothing). The engine's heartbeat reads it every interval and saves it on the attempt
(``provider_metadata.live_activity.workflow``) next to whether the harness process is still alive. Nothing here ends,
retries or judges an attempt: it only shows liveness. A harness that goes quiet is not idle, it may be thinking.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass

THINKING = "thinking"
WRITING = "writing"
WAITING = "waiting"
PROVIDER_RETRY = "provider_retry"


def tool_phase(name: object) -> str:
    """The phase of a tool in flight: ``tool:<name>``."""

    return f"tool:{name}" if name else "tool"


@dataclass
class LiveStatus:
    """The attempt's current phase and the time of the harness's last event (unix seconds; None before the first)."""

    phase: str = WAITING
    last_event_at: float | None = None
    # The harness's own session id and transcript file, as soon as the executor learns them (``note_native``). A
    # transcript that is not located yet comes from ``locate``, which the transcript follower calls off the event loop.
    native_session_id: str | None = None
    transcript_path: str | None = None
    locate: Callable[[], str | None] | None = None

    def note(self, phase: str | None = None, *, at: float | None = None) -> None:
        """Any event is activity; one that also says what the model is doing sets the phase."""

        self.last_event_at = time.time() if at is None else at
        if phase:
            self.phase = phase

    def note_native(
        self,
        session_id: str | None = None,
        transcript_path: str | None = None,
        locate: Callable[[], str | None] | None = None,
    ) -> None:
        """Remember what the harness has said about its own session (a later value replaces an earlier one)."""

        if session_id and session_id != self.native_session_id:
            self.native_session_id = session_id
            if transcript_path is None:
                self.transcript_path = None  # a different session has a different file
            self.locate = locate
        if transcript_path:
            self.transcript_path = transcript_path

    def snapshot(self) -> dict[str, object]:
        return {"phase": self.phase, "last_event_at": self.last_event_at}


# Set by the engine around an attempt, like the process tracker: the executor's task starts with a copy of the context.
current_live: ContextVar[LiveStatus | None] = ContextVar("workflow_live_status", default=None)


def note_live(phase: str | None = None) -> None:
    """Record an event of the running attempt (no-op outside an attempt)."""

    live = current_live.get()
    if live is not None:
        live.note(phase)


def note_native(
    session_id: str | None = None,
    transcript_path: str | None = None,
    locate: Callable[[], str | None] | None = None,
) -> None:
    """Record the harness's native session id and where its transcript is (no-op outside an attempt)."""

    live = current_live.get()
    if live is not None:
        live.note_native(session_id, transcript_path, locate)
