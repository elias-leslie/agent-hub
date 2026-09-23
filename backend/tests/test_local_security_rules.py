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
    source = tmp_path / "processes.py"

    def findings(code: str) -> tuple[int, list[dict[str, object]]]:
        source.write_text(code, encoding="utf-8")
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
                str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        report = json.loads(result.stdout)
        return result.returncode, report["results"]

    safe_status, safe_findings = findings(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(['git', 'status'], shell=False)\n"
        "subprocess.run(['git', 'status'])\n"
        "asyncio.create_subprocess_exec('git', 'status')\n"
    )
    assert safe_status == 0
    assert safe_findings == []

    unsafe_status, unsafe_findings = findings(
        "import asyncio\n"
        "import subprocess\n"
        "subprocess.run(command, shell=True)\n"
        "subprocess.Popen(command, shell=True)\n"
        "asyncio.create_subprocess_shell(command)\n"
    )
    assert unsafe_status == 1
    assert len(unsafe_findings) == 3
    assert all(
        str(item["check_id"]).endswith("agent-hub-python-shell-execution")
        for item in unsafe_findings
    )
