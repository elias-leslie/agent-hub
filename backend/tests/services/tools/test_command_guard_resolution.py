from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.tools.command_guard import _resolve_shared_command_guard_cached


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
        patch("app.services.tools.command_guard.Path") as mock_path,
        patch(
            "app.services.tools.command_guard.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="bash sh", stderr=""),
        ),
    ):
        mock_path.side_effect = lambda value: canonical_scripts_dir if str(value).startswith("/srv/") else Path(value)
        resolved = _resolve_shared_command_guard_cached()

    _resolve_shared_command_guard_cached.cache_clear()
    assert resolved is not None
    assert resolved.guard_bin == str(guard_bin.resolve())
    assert resolved.bash_env == str(bash_env.resolve())
    assert resolved.words == "bash sh"
