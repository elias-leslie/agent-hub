"""Entry-point modules import cleanly, each from a cold ``app`` package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Each group is imported with no ``app.*`` modules cached, so an import cycle
# that pytest's warm module cache would hide still fails here.
_IMPORT_GROUPS = (
    ("app.services.agent_routing", "app.api.complete"),
    ("app.tasks.session_cleanup",),
)

_SCRIPT = """
import importlib, sys
for group in {groups!r}:
    for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[name]
    for module in group:
        importlib.import_module(module)
"""


def test_entry_modules_import_without_cycles() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(groups=_IMPORT_GROUPS)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
