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


def test_absent_guard_does_not_re_resolve_scripts_dir_per_call() -> None:
    """An absent guard is cached; each call must not rerun the ``st`` lookup on the loop."""
    from app.services.tools import command_guard

    _resolve_shared_command_guard_cached.cache_clear()
    with patch.object(command_guard, "resolve_summitflow_scripts_dir", return_value=None) as resolve:
        resolve.cache_clear = lambda: None
        with patch.dict(command_guard.os.environ, {"SUMMITFLOW_SCRIPTS_DIR": ""}):
            assert command_guard.resolve_shared_command_guard() is None
            assert command_guard.resolve_shared_command_guard() is None
    _resolve_shared_command_guard_cached.cache_clear()
    assert resolve.call_count == 1



def test_warm_fills_scripts_dir_cache_so_tool_calls_skip_st(tmp_path: Path) -> None:
    """After the startup warm, tool callers never reach the ``st`` subprocess lookup."""
    from app.core import project_roots
    from app.services.tools import command_guard

    project_roots.resolve_summitflow_scripts_dir.cache_clear()
    _resolve_shared_command_guard_cached.cache_clear()
    with (
        patch.dict(project_roots.os.environ, {"SUMMITFLOW_SCRIPTS_DIR": "", "SUMMITFLOW_ROOT": str(tmp_path)}),
        patch.object(project_roots, "resolve_project_root") as st_lookup,
    ):
        (tmp_path / "scripts").mkdir()
        command_guard.warm_shared_command_guard()
        assert project_roots.resolve_summitflow_scripts_dir() == (tmp_path / "scripts").resolve()
        command_guard.resolve_shared_command_guard()
    project_roots.resolve_summitflow_scripts_dir.cache_clear()
    _resolve_shared_command_guard_cached.cache_clear()
    st_lookup.assert_not_called()
