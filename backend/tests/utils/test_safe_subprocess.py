from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.safe_subprocess import create_process, run_process


def test_run_process_uses_absolute_env_launcher_and_keeps_fds_closed_flag_false() -> None:
    with (
        patch("app.utils.safe_subprocess.shutil.which", return_value="/usr/bin/env"),
        patch(
            "app.utils.safe_subprocess.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="ok", stderr=""),
        ) as mock_run,
    ):
        result = run_process(
            ("st", "--help"),
            cwd=Path("/tmp/project"),
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.stdout == "ok"
    assert mock_run.call_args.args[0] == ["/usr/bin/env", "-C", "/tmp/project", "st", "--help"]
    assert mock_run.call_args.kwargs["close_fds"] is False


@pytest.mark.asyncio
async def test_create_process_uses_absolute_env_launcher_and_keeps_fds_closed_flag_false() -> None:
    fake_process = object()
    with (
        patch("app.utils.safe_subprocess.shutil.which", return_value="/usr/bin/env"),
        patch(
            "app.utils.safe_subprocess.asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
            return_value=fake_process,
        ) as mock_exec,
    ):
        process = await create_process("agent-browser", "open", "http://example.test")

    assert process is fake_process
    assert mock_exec.call_args.args[:3] == ("/usr/bin/env", "agent-browser", "open")
    assert mock_exec.call_args.kwargs["close_fds"] is False
