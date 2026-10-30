"""Executable examples for the narrow local shell-execution rule."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("semgrep") is None, reason="Semgrep is not installed")
def test_shell_rule_flags_shell_execution_and_accepts_argument_vectors(tmp_path: Path) -> None:
    config = Path(__file__).resolve().parents[2] / ".semgrep.yml"
    safe = tmp_path / "safe_processes.py"
    unsafe = tmp_path / "unsafe_processes.py"
    safe.write_text(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(['git', 'status'], shell=False)\n"
        "subprocess.run(['git', 'status'])\n"
        "asyncio.create_subprocess_exec('git', 'status')\n",
        encoding="utf-8",
    )
    unsafe.write_text(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(command, shell=True)\n"
        "subprocess.Popen(command, shell=True)\n"
        "asyncio.create_subprocess_shell(command)\n",
        encoding="utf-8",
    )

    # One scan covers both files: semgrep startup dominates the cost of this test.
    result = subprocess.run(
        [
            "semgrep",
            "scan",
            "--config",
            str(config),
            "--metrics",
            "off",
            "--disable-version-check",
            "--error",
            "--json",
            str(safe),
            str(unsafe),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    report = json.loads(result.stdout)
    assert report["errors"] == []
    assert result.returncode == 1
    findings = report["results"]
    assert [item for item in findings if Path(str(item["path"])).name == safe.name] == []
    unsafe_findings = [item for item in findings if Path(str(item["path"])).name == unsafe.name]
    assert len(unsafe_findings) == len(findings) == 3
    assert all(
        str(item["check_id"]).endswith("agent-hub-python-shell-execution")
        for item in unsafe_findings
    )
