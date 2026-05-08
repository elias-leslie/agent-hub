from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.tools import _executor_bash


class CancelledProcess:
    pid = 12345
    returncode: int | None = None

    async def communicate(self) -> tuple[bytes, bytes]:
        raise asyncio.CancelledError

    async def wait(self) -> int:
        self.returncode = -signal.SIGTERM
        return self.returncode


@pytest.mark.asyncio
async def test_run_bash_terminates_process_group_on_cancel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    process = CancelledProcess()
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(_executor_bash, "create_bash_process", AsyncMock(return_value=process))
    monkeypatch.setattr(_executor_bash.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    with pytest.raises(asyncio.CancelledError):
        await _executor_bash.run_bash("sleep 999", tmp_path, dict(os.environ))

    assert signals == [(process.pid, signal.SIGTERM)]
