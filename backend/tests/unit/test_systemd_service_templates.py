from __future__ import annotations

import importlib.util
import re
from pathlib import Path

SYSTEMD_DIR = Path(__file__).resolve().parents[3] / "scripts" / "systemd"
_MODULE_PATTERN = re.compile(r"(?:python -m |uvicorn )([\w.]+)")


def test_each_execstart_module_is_importable() -> None:
    modules = {
        match.group(1)
        for unit in SYSTEMD_DIR.glob("*.service")
        for line in unit.read_text().splitlines()
        if line.startswith("ExecStart=")
        for match in _MODULE_PATTERN.finditer(line)
    }
    assert modules, "no Python ExecStart modules found"
    missing = sorted(name for name in modules if importlib.util.find_spec(name) is None)
    assert missing == []
