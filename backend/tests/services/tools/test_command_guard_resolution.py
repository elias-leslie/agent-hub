from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.tools.command_guard import (
    SharedCommandGuard,
    _resolve_shared_command_guard_cached,
    get_command_guard_block_reason,
)


def test_resolve_shared_command_guard_falls_back_when_resolved_scripts_lacks_guard(
    tmp_path: Path,
) -> None:
    partial_scripts_dir = tmp_path / "partial-scripts"
    partial_scripts_dir.mkdir()
    canonical_scripts_dir = tmp_path / "summitflow" / "scripts"
    lib_dir = canonical_scripts_dir / "lib"
    lib_dir.mkdir(parents=True)
    guard_bin = lib_dir / "command-guard"
    bash_env = lib_dir / "bash-command-guard.sh"
    guard_bin.write_text("#!/usr/bin/env bash\n")
    bash_env.write_text("#!/usr/bin/env bash\n")

    _resolve_shared_command_guard_cached.cache_clear()
    with (
        patch("app.services.tools.command_guard.resolve_summitflow_scripts_dir", return_value=partial_scripts_dir),
        patch.dict("app.services.tools.command_guard.os.environ", {"SUMMITFLOW_SCRIPTS_DIR": str(canonical_scripts_dir)}),
        patch(
            "app.services.tools.command_guard.run_process",
            return_value=SimpleNamespace(returncode=0, stdout="bash sh", stderr=""),
        ),
    ):
        resolved = _resolve_shared_command_guard_cached()

    _resolve_shared_command_guard_cached.cache_clear()
    assert resolved is not None
    assert resolved.guard_bin == str(guard_bin.resolve())
    assert resolved.bash_env == str(bash_env.resolve())
    assert resolved.words == "bash sh"


def test_block_reason_allows_when_guard_absent() -> None:
    """A missing shared guard must not block bash; the guard simply does not apply."""
    with patch(
        "app.services.tools.command_guard.resolve_shared_command_guard",
        return_value=None,
    ):
        assert get_command_guard_block_reason("rm -rf /tmp/x", Path("/tmp")) is None


def test_block_reason_blocks_when_present_guard_flags_command() -> None:
    """A present guard that flags a command (returncode 2) still blocks."""
    resolved = SharedCommandGuard(
        guard_bin="/x/lib/command-guard",
        bash_env="/x/lib/bash-command-guard.sh",
        words="rm",
    )
    with (
        patch("app.services.tools.command_guard.resolve_shared_command_guard", return_value=resolved),
        patch(
            "app.services.tools.command_guard.run_process",
            return_value=SimpleNamespace(returncode=2, stdout="blocked: rm is dangerous", stderr=""),
        ),
    ):
        reason = get_command_guard_block_reason("rm -rf /tmp/x", Path("/tmp"))
    assert reason == "blocked: rm is dangerous"


def test_block_reason_blocks_when_present_guard_errors() -> None:
    """A present-but-broken guard fails closed, so it is never silently bypassed."""
    resolved = SharedCommandGuard(
        guard_bin="/x/lib/command-guard",
        bash_env="/x/lib/bash-command-guard.sh",
        words="rm",
    )
    with (
        patch("app.services.tools.command_guard.resolve_shared_command_guard", return_value=resolved),
        patch("app.services.tools.command_guard.run_process", side_effect=OSError("boom")),
    ):
        reason = get_command_guard_block_reason("rm -rf /tmp/x", Path("/tmp"))
    assert reason is not None
    assert "boom" in reason
