"""Helpers for normalizing live session file/path scope."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from app.models import Session
from app.services.tools.project_env import detect_main_repo

_SCOPE_CONFIDENCE_RANK = {
    "unknown": 0,
    "observed_read": 1,
    "observed_write": 2,
    "declared": 3,
}


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


def resolve_scope_base_path(
    metadata: dict[str, Any] | None,
    cwd: str | None,
) -> str | None:
    """Resolve the best repo/worktree base path for scope normalization."""
    payload = metadata if isinstance(metadata, dict) else {}
    for key in ("worktree_path", "repo_root", "cwd"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return cwd


def resolve_scope_confidence(
    explicit: str | None,
    declared_scope_paths: list[str] | None,
    observed_write_paths: list[str] | None,
    observed_read_paths: list[str] | None,
    existing: str | None = None,
) -> str:
    """Resolve the strongest available scope confidence value."""
    if explicit in _SCOPE_CONFIDENCE_RANK:
        return explicit
    derived = "unknown"
    if declared_scope_paths:
        derived = "declared"
    elif observed_write_paths:
        derived = "observed_write"
    elif observed_read_paths:
        derived = "observed_read"
    if existing in _SCOPE_CONFIDENCE_RANK and _SCOPE_CONFIDENCE_RANK[existing] > _SCOPE_CONFIDENCE_RANK[derived]:
        return existing
    return derived


def apply_scope_state(
    session: Session,
    *,
    base_path: str | None,
    declared_scope_paths: list[str] | None = None,
    observed_read_paths: list[str] | None = None,
    observed_write_paths: list[str] | None = None,
    scope_confidence: str | None = None,
) -> None:
    """Merge declared and observed scope paths onto a session row."""
    normalized_declared = normalize_scope_paths(declared_scope_paths, base_path)
    normalized_reads = normalize_scope_paths(observed_read_paths, base_path)
    normalized_writes = normalize_scope_paths(observed_write_paths, base_path)

    if normalized_declared:
        session.declared_scope_paths = normalized_declared
    elif session.declared_scope_paths is None:
        session.declared_scope_paths = []

    if normalized_reads:
        session.observed_read_paths = merge_scope_paths(session.observed_read_paths, normalized_reads)
    elif session.observed_read_paths is None:
        session.observed_read_paths = []

    if normalized_writes:
        session.observed_write_paths = merge_scope_paths(session.observed_write_paths, normalized_writes)
    elif session.observed_write_paths is None:
        session.observed_write_paths = []

    session.scope_confidence = resolve_scope_confidence(
        scope_confidence,
        session.declared_scope_paths,
        session.observed_write_paths,
        session.observed_read_paths,
        session.scope_confidence,
    )
