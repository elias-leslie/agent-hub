"""Project environment resolution for tool execution."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.services.tools.command_guard import build_command_guard_env_overlay

logger = logging.getLogger(__name__)


def detect_repo_root(working_dir: Path) -> Path | None:
    """Return the nearest git checkout root for a working directory."""
    current = working_dir.resolve()
    for candidate in (current, *current.parents):
        git_path = candidate / ".git"
        if git_path.exists():
            return candidate
    return None


def find_venv(working_dir: Path, repo_root: Path | None = None) -> Path | None:
    """Find the Python venv for a project directory.

    Checks working_dir first, then repo_root when different.
    Returns the venv directory (not the bin/python path).
    """
    candidates = [
        working_dir / "backend" / ".venv",
        working_dir / ".venv",
    ]
    if repo_root and repo_root != working_dir:
        candidates.extend([
            repo_root / "backend" / ".venv",
            repo_root / ".venv",
        ])

    for venv_path in candidates:
        python_bin = venv_path / "bin" / "python"
        if python_bin.exists():
            return venv_path

    return None


def build_project_env(working_dir: str | Path) -> dict[str, str]:
    """Build an environment dict with the correct project venv on PATH.

    This is the single source of truth for "what environment should
    subprocess commands use in this directory."

    Returns a copy of os.environ with VIRTUAL_ENV, PATH, and PYTHONHOME
    adjusted for the project's venv. If no venv found, returns os.environ
    copy unchanged (bare python will be used).
    """
    working_dir = Path(working_dir).resolve()
    env = os.environ.copy()

    repo_root = detect_repo_root(working_dir)
    venv_path = find_venv(working_dir, repo_root)

    if not venv_path:
        if repo_root:
            logger.debug("No venv found for %s (repo root: %s)", working_dir, repo_root)
        env.update(build_command_guard_env_overlay())
        return env

    venv_bin = str(venv_path / "bin")
    env["VIRTUAL_ENV"] = str(venv_path)
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)
    env.update(build_command_guard_env_overlay())

    logger.debug(
        "Resolved project venv: %s (working_dir=%s, repo_root=%s)",
        venv_path,
        working_dir,
        repo_root,
    )
    return env


def build_venv_env_overlay(working_dir: str | Path) -> dict[str, str]:
    """Build env var overlay for venv activation (for SDK merge).

    Unlike build_project_env() which returns a full os.environ copy,
    this returns ONLY the keys that need to change. This is designed
    for callers that merge with os.environ themselves.

    Returns empty dict if no venv found.
    """
    working_dir = Path(working_dir).resolve()
    repo_root = detect_repo_root(working_dir)
    venv_path = find_venv(working_dir, repo_root)

    if not venv_path:
        return build_command_guard_env_overlay()

    venv_bin = str(venv_path / "bin")
    overlay: dict[str, str] = {
        "VIRTUAL_ENV": str(venv_path),
        "PATH": f"{venv_bin}:{os.environ.get('PATH', '')}",
        "PYTHONHOME": "",  # Empty string overrides os.environ's value in SDK merge
    }
    overlay.update(build_command_guard_env_overlay())

    logger.info(
        "Venv env overlay: %s (working_dir=%s, repo_root=%s)",
        venv_path,
        working_dir,
        repo_root,
    )
    return overlay


# Project ownership of a path (which registered project's root contains it)

def path_within_root(resolved_path: str, root: str) -> bool:
    """Return True when *resolved_path* is inside *root*."""
    try:
        Path(resolved_path).relative_to(Path(root))
        return True
    except ValueError:
        return False


def find_target_project(resolved_path: str, known_roots: dict[str, str]) -> str | None:
    """Return the project ID whose root contains *resolved_path*, or None."""
    roots_by_specificity = sorted(
        ((proj_id, root) for proj_id, root in known_roots.items() if root),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for proj_id, root in roots_by_specificity:
        if path_within_root(resolved_path, root):
            return proj_id
    return None


def resolve_checkout_owner_root(path: Path) -> Path | None:
    """Return canonical repo root when *path* is inside a linked git checkout."""
    repo_root = detect_repo_root(path if path.is_dir() else path.parent)
    if repo_root is None:
        return None

    git_path = repo_root / ".git"
    if not git_path.is_file():
        return repo_root

    try:
        first_line = git_path.read_text().splitlines()[0].strip()
    except (OSError, IndexError):
        return repo_root

    prefix = "gitdir:"
    if not first_line.startswith(prefix):
        return repo_root

    gitdir = Path(first_line[len(prefix):].strip())
    if not gitdir.is_absolute():
        gitdir = (repo_root / gitdir).resolve()

    if gitdir.parent.name == "checkouts" and gitdir.parent.parent.name == ".git":
        return gitdir.parent.parent.parent.resolve()
    return repo_root


def infer_target_project(path: Path, known_roots: dict[str, str]) -> str | None:
    """Infer the owning project for a resolved path."""
    if owner_root := resolve_checkout_owner_root(path):
        target_project = find_target_project(str(owner_root), known_roots)
        if target_project:
            return target_project
    resolved_path = str(path.resolve(strict=False))
    return find_target_project(resolved_path, known_roots)
