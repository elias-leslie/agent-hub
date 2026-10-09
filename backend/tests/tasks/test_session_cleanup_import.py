"""The session-cleanup step imports cleanly in a fresh worker process."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_session_cleanup_imports_without_a_cycle() -> None:
    # A fresh interpreter: pytest's module cache would hide an import cycle.
    result = subprocess.run(
        [sys.executable, "-c", "import app.tasks.session_cleanup"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
