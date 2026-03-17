"""Project environment resolution for tool execution.

Detects the correct Python virtual environment for a working directory,
handling git worktrees transparently. Worktrees share the main repo's
.venv — this module finds it regardless of whether we're in the main
repo or a worktree.

Detection approach (from claude-mem reference):
  - .git is a directory → main repo
  - .git is a file containing "gitdir: ..." → worktree, parse to find parent

Venv search order:
  1. working_dir/backend/.venv
  2. working_dir/.venv
  3. (if worktree) main_repo/backend/.venv
  4. (if worktree) main_repo/.venv
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def detect_main_repo(working_dir: Path) -> Path | None:
    """If working_dir is a git worktree, return the main repo path.

    Git worktrees have a .git FILE (not directory) containing:
        gitdir: /path/to/parent/.git/worktrees/<name>

    Returns None if working_dir is the main repo or not a git repo.
    """
    git_path = working_dir / ".git"
    if not git_path.exists():
        return None
    if git_path.is_dir():
        return None

    try:
        content = git_path.read_text().strip()
    except OSError:
        return None

    match = re.match(r"^gitdir:\s*(.+)$", content)
    if not match:
        return None

    gitdir = match.group(1)
    worktree_match = re.match(r"^(.+)[/\\]\.git[/\\]worktrees[/\\][^/\\]+$", gitdir)
    if not worktree_match:
        return None

    parent = Path(worktree_match.group(1))
    if parent.exists():
        return parent
    return None


def is_worktree_path(path: str | None) -> bool:
    """Return True if the given path is inside a git worktree."""
    if not path:
        return False
    try:
        return detect_main_repo(Path(path).resolve()) is not None
    except OSError:
        return False


def find_venv(working_dir: Path, main_repo: Path | None = None) -> Path | None:
    """Find the Python venv for a project directory.

    Checks working_dir first, then main_repo (for worktrees).
    Returns the venv directory (not the bin/python path).
    """
    candidates = [
        working_dir / "backend" / ".venv",
        working_dir / ".venv",
    ]
    if main_repo and main_repo != working_dir:
        candidates.extend([
            main_repo / "backend" / ".venv",
            main_repo / ".venv",
        ])

    for venv_path in candidates:
        python_bin = venv_path / "bin" / "python"
        if python_bin.exists():
            return venv_path

    return None


def build_project_env(working_dir: str | Path) -> dict[str, str]:
    """Build an environment dict with the correct project venv on PATH.

    This is the single source of truth for "what environment should
    subprocess commands use in this directory." Handles:
    - Main repos (finds local .venv)
    - Worktrees (finds main repo's .venv)
    - Non-Python projects (returns base env unchanged)

    Returns a copy of os.environ with VIRTUAL_ENV, PATH, and PYTHONHOME
    adjusted for the project's venv. If no venv found, returns os.environ
    copy unchanged (bare python will be used).
    """
    working_dir = Path(working_dir).resolve()
    env = os.environ.copy()

    main_repo = detect_main_repo(working_dir)
    venv_path = find_venv(working_dir, main_repo)

    if not venv_path:
        if main_repo:
            logger.debug(
                "No venv found for worktree %s (main repo: %s)",
                working_dir,
                main_repo,
            )
        return env

    venv_bin = str(venv_path / "bin")
    env["VIRTUAL_ENV"] = str(venv_path)
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)

    logger.info(
        "Resolved project venv: %s (working_dir=%s, worktree=%s)",
        venv_path,
        working_dir,
        main_repo is not None,
    )
    return env


def build_venv_env_overlay(working_dir: str | Path) -> dict[str, str]:
    """Build env var overlay for venv activation (for SDK merge).

    Unlike build_project_env() which returns a full os.environ copy,
    this returns ONLY the keys that need to change. This is designed
    for callers that merge with os.environ themselves (e.g. Claude SDK
    does ``{**os.environ, **options.env}``).

    Returns empty dict if no venv found.
    """
    working_dir = Path(working_dir).resolve()
    main_repo = detect_main_repo(working_dir)
    venv_path = find_venv(working_dir, main_repo)

    if not venv_path:
        return {}

    venv_bin = str(venv_path / "bin")
    overlay: dict[str, str] = {
        "VIRTUAL_ENV": str(venv_path),
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
        "PYTHONHOME": "",  # Empty string overrides os.environ's value in SDK merge
    }

    logger.info(
        "Venv env overlay: %s (working_dir=%s, worktree=%s)",
        venv_path,
        working_dir,
        main_repo is not None,
    )
    return overlay
