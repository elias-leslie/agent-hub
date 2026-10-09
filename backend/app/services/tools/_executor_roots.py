"""Project root directory proxy for the direct tool executor.

Provides a dict-like proxy over get_known_roots() so callers that import
KNOWN_ROOTS always see the current cached project-root mapping.
"""

from __future__ import annotations

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


def _linked_worktrees(roots: list[Path]) -> list[Path]:
    """Linked git worktrees of the known roots, read from each root's own git records."""
    worktrees: list[Path] = []
    for root in roots:
        records = root / ".git" / "worktrees"
        if not records.is_dir():
            continue
        for gitdir_file in records.glob("*/gitdir"):
            try:
                worktrees.append(Path(gitdir_file.read_text().strip()).resolve().parent)
            except OSError:
                continue
    return worktrees


def contained_working_dir(working_dir: str) -> Path:
    """Resolve a caller-supplied working directory inside an allowed root.

    Allowed: a known project root, a linked git worktree of one, or the system
    temporary directory (scratch). Anything else raises ``ValueError`` before the
    path is touched; the directory is never created.
    """
    directory = Path(working_dir).resolve()
    roots = [Path(root).resolve() for root in _get_known_roots().values()]
    bases = [*roots, Path(tempfile.gettempdir()).resolve()]
    if not any(directory.is_relative_to(base) for base in bases) and not any(
        directory.is_relative_to(worktree) for worktree in _linked_worktrees(roots)
    ):
        raise ValueError(f"working_dir {working_dir!r} is outside the known project roots and scratch")
    if not directory.is_dir():
        raise ValueError(f"working_dir {working_dir!r} is not an existing directory")
    return directory
