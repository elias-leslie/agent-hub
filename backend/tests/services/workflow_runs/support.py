"""Test helpers shared by the workflow executor suites: a clock that can jump hours ahead, and a phase recorder."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager

from app.services.workflow_runs.live import LiveStatus, current_live


class LoopClock:
    """The running event loop's clock with a settable offset.

    Every ``asyncio.wait_for`` and ``call_later`` deadline is measured on ``loop.time()``, so a jump of two hours makes
    any wall-clock limit a step had fire on the next loop iteration, without sleeping for it.
    """

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._real = self.loop.time
        self.offset = 0.0
        self.loop.time = lambda: self._real() + self.offset  # type: ignore[method-assign]

    def jump(self, seconds: float) -> None:
        self.offset += seconds

    def restore(self) -> None:
        self.loop.time = self._real  # type: ignore[method-assign]


@contextmanager
def loop_clock() -> Iterator[LoopClock]:
    clock = LoopClock()
    try:
        yield clock
    finally:
        clock.restore()


class PhaseRecorder(LiveStatus):
    """A LiveStatus that also keeps every phase it was told, in order, consecutive repeats collapsed."""

    def __init__(self) -> None:
        super().__init__()
        self.history: list[str] = []

    def note(self, phase: str | None = None, *, at: float | None = None) -> None:
        super().note(phase, at=at)
        if phase and (not self.history or self.history[-1] != phase):
            self.history.append(phase)


@contextmanager
def recording_live() -> Iterator[PhaseRecorder]:
    live = PhaseRecorder()
    token = current_live.set(live)
    try:
        yield live
    finally:
        current_live.reset(token)
