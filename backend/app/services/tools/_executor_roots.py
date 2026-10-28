"""Project root directory proxy for the direct tool executor.

Provides a dict-like proxy over get_known_roots() so callers that import
KNOWN_ROOTS always see the current cached project-root mapping.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def _get_known_roots() -> dict[str, str]:
    """Get project_id → root_path mapping from cached project data."""
    from app.constants.projects import get_known_roots

    return get_known_roots()


class _RootsProxy(dict):
    """Dict-like proxy that delegates to get_known_roots()."""

    def get(self, key: str, default: str | None = None) -> str | None:
        return _get_known_roots().get(key, default)

    def __getitem__(self, key: str) -> str:
        return _get_known_roots()[key]

    def __contains__(self, key: object) -> bool:
        return key in _get_known_roots()

    def __iter__(self):
        return iter(_get_known_roots())

    def items(self):
        return _get_known_roots().items()

    def values(self):
        return _get_known_roots().values()

    def keys(self):
        return _get_known_roots().keys()

    def __repr__(self) -> str:
        return repr(_get_known_roots())


KNOWN_ROOTS: dict[str, str] = _RootsProxy()


def _workflow_runs_root() -> str:
    """Agent Hub's own workflow-run directory (configured, created by the engine): run worktrees and plain run dirs."""
    from app.services.workflow_runs.settings import get_workflow_run_settings

    return str(get_workflow_run_settings().runs_root)


def _linked_worktrees(roots: list[str]) -> list[str]:
    """Real paths of the known roots' linked git worktrees, read from each root's own git records."""
    worktrees: list[str] = []
    for root in roots:
        records = os.path.join(root, ".git", "worktrees")
        if not os.path.isdir(records):
            continue
        for name in os.listdir(records):
            try:
                with open(os.path.join(records, name, "gitdir")) as gitdir_file:
                    gitdir = gitdir_file.read().strip()
            except OSError:
                continue
            worktrees.append(os.path.dirname(os.path.realpath(gitdir)))
    return worktrees


def contained_working_dir(working_dir: str) -> Path:
    """Resolve a caller-supplied working directory inside an allowed root.

    Allowed: a known project root, a linked git worktree of one, the workflow runs
    root, or the system temporary directory (scratch). Anything else raises ``ValueError`` before the
    path is touched; the directory is never created.
    """
    real = os.path.realpath(working_dir)
    roots = [os.path.realpath(root) for root in _get_known_roots().values()]
    bases = [*roots, os.path.realpath(_workflow_runs_root()), os.path.realpath(tempfile.gettempdir())]
    allowed = bases + _linked_worktrees(roots)
    # Exactly a root: return the trusted configured value, not the caller's.
    for base in allowed:
        if base == real:
            return _existing_directory(Path(base), working_dir)
    for base in allowed:
        prefix = base.rstrip(os.sep) + os.sep
        if not real.startswith(prefix):
            continue
        directory = Path(real)
        if not directory.is_dir():
            raise ValueError(f"working_dir {working_dir!r} is not an existing directory")
        return directory
    raise ValueError(f"working_dir {working_dir!r} is outside the known project roots and scratch")


def _existing_directory(directory: Path, working_dir: str) -> Path:
    if not directory.is_dir():
        raise ValueError(f"working_dir {working_dir!r} is not an existing directory")
    return directory
