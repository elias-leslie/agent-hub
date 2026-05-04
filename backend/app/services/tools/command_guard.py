"""Thin adapter for SummitFlow's shared shell command guard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.project_roots import resolve_summitflow_scripts_dir
from app.utils.safe_subprocess import run_process


@dataclass(frozen=True)
class SharedCommandGuard:
    """Resolved shared command guard assets."""

    guard_bin: str
    bash_env: str
    words: str


def _guard_assets_exist(resolved: SharedCommandGuard | None) -> bool:
    if resolved is None:
        return False
    return Path(resolved.guard_bin).exists() and Path(resolved.bash_env).exists()


@lru_cache(maxsize=1)
def _resolve_shared_command_guard_cached() -> SharedCommandGuard | None:
    """Resolve the shared command guard binaries and intercept metadata."""
    scripts_dirs = []
    scripts_dir = resolve_summitflow_scripts_dir()
    if scripts_dir is not None:
        scripts_dirs.append(scripts_dir)
    canonical_scripts_dir = Path("/srv/workspaces/projects/summitflow/scripts")
    if canonical_scripts_dir not in scripts_dirs:
        scripts_dirs.append(canonical_scripts_dir)

    for scripts_dir in scripts_dirs:
        guard_bin = (scripts_dir / "lib" / "command-guard").resolve()
        bash_env = (scripts_dir / "lib" / "bash-command-guard.sh").resolve()
        if guard_bin.exists() and bash_env.exists():
            break
    else:
        return None

    try:
        result = run_process(
            [str(guard_bin), "--emit-intercept-words"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "BASH_ENV": "", "SF_COMMAND_GUARD_DISABLE": "1"},
        )
    except OSError:
        return None

    if result.returncode != 0:
        return None
    words = result.stdout.strip()
    if not words:
        return None
    return SharedCommandGuard(
        guard_bin=str(guard_bin),
        bash_env=str(bash_env),
        words=words,
    )


def resolve_shared_command_guard() -> SharedCommandGuard | None:
    """Resolve the shared command guard binaries and recover from stale cached paths."""
    resolved = _resolve_shared_command_guard_cached()
    if _guard_assets_exist(resolved):
        return resolved

    resolve_summitflow_scripts_dir.cache_clear()
    _resolve_shared_command_guard_cached.cache_clear()

    resolved = _resolve_shared_command_guard_cached()
    return resolved if _guard_assets_exist(resolved) else None


def build_command_guard_env_overlay() -> dict[str, str]:
    """Return env vars that enable the shared bash command guard."""
    resolved = resolve_shared_command_guard()
    if resolved is None:
        return {}

    overlay = {
        "SUMMITFLOW_SCRIPTS_DIR": str(Path(resolved.guard_bin).resolve().parents[1]),
        "SF_COMMAND_GUARD_BIN": resolved.guard_bin,
        "SF_COMMAND_GUARD_WORDS": resolved.words,
        "BASH_ENV": resolved.bash_env,
    }
    previous = os.environ.get("BASH_ENV", "").strip()
    if previous and previous != resolved.bash_env:
        overlay["SF_COMMAND_GUARD_PREV_BASH_ENV"] = previous
    return overlay


def get_command_guard_block_reason(
    command: str,
    working_dir: Path,
    *,
    session_id: str | None = None,
) -> str | None:
    """Return a shared-guard block reason for the command, or None if allowed."""
    resolved = resolve_shared_command_guard()
    if resolved is None:
        return "Shared command guard unavailable"

    env = {**os.environ, "BASH_ENV": "", "SF_COMMAND_GUARD_DISABLE": "1"}
    if session_id:
        env["AGENT_HUB_SESSION_ID"] = session_id

    try:
        result = run_process(
            [
                resolved.guard_bin,
                "--shell-command",
                command,
                "--cwd",
                str(working_dir.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        return f"Shared command guard failed: {exc}"

    if result.returncode == 0:
        return None
    message = result.stdout.strip() or result.stderr.strip()
    if result.returncode == 2:
        return message or "Command blocked for safety"
    return message or "Shared command guard failed"
