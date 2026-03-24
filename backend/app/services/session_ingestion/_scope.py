"""Scope state helpers for session ingestion."""

from __future__ import annotations

from typing import Any

from app.models import Session
from app.services.session_scope import merge_scope_paths, normalize_scope_paths

_SCOPE_CONFIDENCE_RANK = {
    "unknown": 0,
    "observed_read": 1,
    "observed_write": 2,
    "declared": 3,
}


def _scope_base_path(
    metadata: dict[str, Any] | None,
    cwd: str | None,
) -> str | None:
    payload = metadata if isinstance(metadata, dict) else {}
    for key in ("worktree_path", "repo_root", "cwd"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return cwd


def _resolve_scope_confidence(
    explicit: str | None,
    declared_scope_paths: list[str] | None,
    observed_write_paths: list[str] | None,
    observed_read_paths: list[str] | None,
    existing: str | None = None,
) -> str:
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


def _apply_scope_state(
    session: Session,
    *,
    base_path: str | None,
    declared_scope_paths: list[str] | None = None,
    observed_read_paths: list[str] | None = None,
    observed_write_paths: list[str] | None = None,
    scope_confidence: str | None = None,
) -> None:
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

    session.scope_confidence = _resolve_scope_confidence(
        scope_confidence,
        session.declared_scope_paths,
        session.observed_write_paths,
        session.observed_read_paths,
        session.scope_confidence,
    )
