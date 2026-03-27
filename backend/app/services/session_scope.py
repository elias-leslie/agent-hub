"""Helpers for normalizing live session file/path scope."""

from __future__ import annotations

import re
import shlex
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
_CONTROL_TOKENS = frozenset({"&&", "||", "|", ";"})
_PATCH_HEADER_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
_PATCH_MOVE_RE = re.compile(r"^\*\*\* Move to: (.+)$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")


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


def _append_unique_path(paths: list[str], candidate: str | None) -> None:
    if candidate and candidate not in paths:
        paths.append(candidate)


def _tool_command(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("command", "cmd"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tool_base_path(tool_input: dict[str, Any] | None, base_path: str | None) -> str | None:
    if not isinstance(tool_input, dict):
        return base_path
    for key in ("workdir", "cwd"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return base_path


def _normalize_tool_scope_path(
    raw_path: Any,
    *,
    base_path: str | None,
    allow_missing: bool,
) -> str | None:
    if not isinstance(raw_path, str):
        return None
    candidate = raw_path.strip().rstrip(",);")
    if not candidate or candidate in _CONTROL_TOKENS or candidate in {"--", ".", ".."}:
        return None
    if ":" in candidate and not candidate.startswith(("/", "./", "../")):
        _, _, possible_path = candidate.partition(":")
        if possible_path:
            candidate = possible_path
    if not candidate or candidate.startswith("-"):
        return None
    if candidate.startswith("/"):
        resolved = Path(candidate).resolve(strict=False)
        if allow_missing or resolved.exists():
            return normalize_scope_path(str(resolved), base_path)
        return None
    if "\\" in candidate or "//" in candidate:
        return None
    if base_path:
        resolved = (Path(base_path) / candidate).resolve(strict=False)
        if allow_missing or resolved.exists():
            return normalize_scope_path(str(resolved), base_path)
        return None
    relative = Path(candidate)
    if allow_missing or relative.exists():
        return normalize_scope_path(str(relative.resolve(strict=False)), None)
    return None


def _extract_explicit_tool_paths(
    tool_input: dict[str, Any] | None,
    *,
    base_path: str | None,
) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    raw_paths: list[Any] = []
    for key in ("file_path", "path", "target_file"):
        raw_paths.append(tool_input.get(key))
    for key in ("file_paths", "paths"):
        value = tool_input.get(key)
        if isinstance(value, list):
            raw_paths.extend(value)
    normalized: list[str] = []
    for raw_path in raw_paths:
        _append_unique_path(
            normalized,
            _normalize_tool_scope_path(raw_path, base_path=base_path, allow_missing=True),
        )
    return normalized


def _split_command_tokens(command: str) -> tuple[list[str], int | None]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return [], None
    command_index: int | None = None
    for index, token in enumerate(tokens):
        if token in _CONTROL_TOKENS:
            break
        if _ENV_ASSIGNMENT_RE.match(token):
            continue
        command_index = index
        break
    return tokens, command_index


def _command_scope_kind(tokens: list[str], command_index: int | None) -> str:
    if command_index is None or command_index >= len(tokens):
        return "read"
    command_name = Path(tokens[command_index]).name.lower()
    if command_name in {"cp", "mkdir", "mv", "rm", "tee", "touch", "truncate"}:
        return "write"
    if command_name == "sed" and any(token == "-i" or token.startswith("-i") for token in tokens[command_index + 1 :]):
        return "write"
    if command_name != "git":
        return "read"
    remainder = tokens[command_index + 1 :]
    subcommand = next(
        (
            token.lower()
            for token in remainder
            if token not in _CONTROL_TOKENS and token != "--" and not token.startswith("-")
        ),
        "",
    )
    return "write" if subcommand in {"checkout", "restore", "revert", "rm"} else "read"


def _extract_command_tool_paths(
    command: str | None,
    *,
    base_path: str | None,
) -> tuple[str, list[str]]:
    if not isinstance(command, str) or not command:
        return "read", []
    tokens, command_index = _split_command_tokens(command)
    if command_index is None:
        return "read", []
    command_name = Path(tokens[command_index]).name.lower()
    candidate_tokens: list[str] = []
    skip_rg_pattern = command_name == "rg"
    saw_rg_pattern = False
    for token in tokens[command_index + 1 :]:
        if token in _CONTROL_TOKENS:
            break
        if token == "--":
            continue
        if token.startswith("-"):
            continue
        if skip_rg_pattern and not saw_rg_pattern:
            saw_rg_pattern = True
            continue
        candidate_tokens.append(token)

    normalized: list[str] = []
    for token in candidate_tokens:
        _append_unique_path(
            normalized,
            _normalize_tool_scope_path(token, base_path=base_path, allow_missing=False),
        )
    return _command_scope_kind(tokens, command_index), normalized


def _extract_apply_patch_paths(
    tool_input: dict[str, Any] | None,
    *,
    base_path: str | None,
) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    payload = tool_input.get("input")
    if not isinstance(payload, str) or "*** Begin Patch" not in payload:
        return []
    paths: list[str] = []
    for line in payload.splitlines():
        match = _PATCH_HEADER_RE.match(line) or _PATCH_MOVE_RE.match(line)
        if not match:
            continue
        _append_unique_path(
            paths,
            _normalize_tool_scope_path(match.group(1), base_path=base_path, allow_missing=True),
        )
    return paths


def extract_tool_scope_paths(
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    *,
    base_path: str | None,
) -> tuple[list[str], list[str]]:
    """Derive normalized read/write scope paths from a tool invocation."""
    normalized_tool = (tool_name or "").strip().lower()
    resolved_base_path = _tool_base_path(tool_input, base_path)
    explicit_paths = _extract_explicit_tool_paths(tool_input, base_path=resolved_base_path)
    patch_paths = _extract_apply_patch_paths(tool_input, base_path=resolved_base_path)
    command_kind, command_paths = _extract_command_tool_paths(
        _tool_command(tool_input),
        base_path=resolved_base_path,
    )

    if "read" in normalized_tool or normalized_tool == "view_image":
        return merge_scope_paths(explicit_paths), []
    if "write" in normalized_tool or "edit" in normalized_tool or normalized_tool == "apply_patch":
        return [], merge_scope_paths(explicit_paths, patch_paths)
    if normalized_tool in {"bash", "exec_command"}:
        if command_kind == "write":
            return [], merge_scope_paths(command_paths)
        return merge_scope_paths(command_paths), []
    return [], []


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
