"""Helpers for normalizing live session file/path scope."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from app.services.tools.project_env import detect_main_repo


def normalize_scope_path(raw_path: Any, base_path: str | None) -> str | None:
    """Normalize a raw path into repo/worktree-relative POSIX form."""
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    if not path:
        return None
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("/"):
        base_candidates: list[Path] = []
        if base_path:
            cwd = Path(base_path).resolve()
            base_candidates.append(cwd)
            main_repo = detect_main_repo(cwd)
            if main_repo and main_repo != cwd:
                base_candidates.append(main_repo.resolve())
        absolute = Path(path).resolve()
        for base in base_candidates:
            try:
                rel = absolute.relative_to(base)
            except ValueError:
                continue
            return normalize_scope_path(str(rel), None)
        return None
    if "\\" in path or "//" in path or path.endswith("/"):
        return None
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    normalized = str(PurePosixPath(path))
    return None if normalized == "." else normalized


def normalize_scope_paths(raw_paths: list[Any] | None, base_path: str | None) -> list[str]:
    """Return unique normalized scope paths while preserving first-seen order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths or []:
        path = normalize_scope_path(raw_path, base_path)
        if path and path not in seen:
            seen.add(path)
            normalized.append(path)
    return normalized


def merge_scope_paths(*groups: list[str] | None) -> list[str]:
    """Merge normalized scope path groups into a unique sorted list."""
    merged = {path for group in groups for path in (group or []) if isinstance(path, str) and path}
    return sorted(merged)

