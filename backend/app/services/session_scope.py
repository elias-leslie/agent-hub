"""Helpers for normalizing live session file/path scope."""

from __future__ import annotations

import re
import shlex
from pathlib import Path, PurePosixPath
from typing import Any

from app.models import Session
from app.services.tools.project_env import detect_repo_root

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


def _safe_resolve(path: Path) -> Path | None:
    """Resolve a path, ignoring invalid filesystem tokens."""
    try:
        return path.resolve(strict=False)
    except OSError:
        return None


def _safe_exists(path: Path) -> bool:
    """Return whether a path exists without surfacing invalid-path OS errors."""
    try:
        return path.exists()
    except OSError:
        return False


def _resolve_to_normalized(path_str: str, base_path: str | None, *, allow_missing: bool) -> str | None:
    """Resolve path_str to absolute and normalize relative to base_path."""
    resolved = _safe_resolve(Path(path_str))
    if resolved is None:
        return None
    if allow_missing or _safe_exists(resolved):
        return normalize_scope_path(str(resolved), base_path)
    return None


def _build_base_candidates(base_path: str) -> list[Path]:
    """Build candidate base paths for relativizing absolute paths."""
    cwd = _safe_resolve(Path(base_path))
    if cwd is None:
        return []
    candidates: list[Path] = [cwd]
    repo_root = detect_repo_root(cwd)
    if repo_root and repo_root != cwd:
        resolved = _safe_resolve(repo_root)
        if resolved is not None:
            candidates.append(resolved)
    return candidates


def normalize_scope_path(raw_path: Any, base_path: str | None) -> str | None:
    """Normalize a raw path into repo-relative POSIX form."""
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    if not path:
        return None
    while path.startswith("./"):
        path = path[2:]
    if path.startswith("/"):
        base_candidates = _build_base_candidates(base_path) if base_path else []
        absolute = _safe_resolve(Path(path))
        if absolute is None:
            return None
        for base in base_candidates:
            if absolute.is_relative_to(base):
                return normalize_scope_path(str(absolute.relative_to(base)), None)
        return None
    if "\\" in path or "//" in path or path.endswith("/"):
        return None
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return None
    normalized = str(PurePosixPath(path))
    return None if normalized == "." else normalized


def normalize_scope_paths(raw_paths: list[Any] | None, base_path: str | None) -> list[str]:
    """Return unique normalized scope paths while preserving first-seen order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths or []:
        p = normalize_scope_path(raw, base_path)
        if p and p not in seen:
            seen.add(p)
            normalized.append(p)
    return normalized


def merge_scope_paths(*groups: list[str] | None) -> list[str]:
    """Merge normalized scope path groups into a unique sorted list."""
    return sorted({p for g in groups for p in (g or []) if isinstance(p, str) and p})


def _append_unique_path(paths: list[str], candidate: str | None) -> None:
    if candidate and candidate not in paths:
        paths.append(candidate)


def _tool_command(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("command", "cmd"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _tool_base_path(tool_input: dict[str, Any] | None, base_path: str | None) -> str | None:
    if not isinstance(tool_input, dict):
        return base_path
    for key in ("workdir", "cwd"):
        v = tool_input.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return base_path


def _normalize_tool_scope_path(raw_path: Any, *, base_path: str | None, allow_missing: bool) -> str | None:
    if not isinstance(raw_path, str):
        return None
    candidate = raw_path.strip().rstrip(",);")
    if not candidate or candidate in _CONTROL_TOKENS or candidate in {"--", ".", ".."}:
        return None
    if ":" in candidate and not candidate.startswith(("/", "./", "../")):
        _, _, tail = candidate.partition(":")
        if tail:
            candidate = tail
    if not candidate or candidate.startswith("-"):
        return None
    if candidate.startswith("/"):
        return _resolve_to_normalized(candidate, base_path, allow_missing=allow_missing)
    if "\\" in candidate or "//" in candidate:
        return None
    if base_path:
        return _resolve_to_normalized(str(Path(base_path) / candidate), base_path, allow_missing=allow_missing)
    return _resolve_to_normalized(candidate, None, allow_missing=allow_missing)


def _extract_explicit_tool_paths(tool_input: dict[str, Any] | None, *, base_path: str | None) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    raw: list[Any] = [tool_input.get(k) for k in ("file_path", "path", "target_file")]
    for key in ("file_paths", "paths"):
        v = tool_input.get(key)
        if isinstance(v, list):
            raw.extend(v)
    normalized: list[str] = []
    for rp in raw:
        _append_unique_path(normalized, _normalize_tool_scope_path(rp, base_path=base_path, allow_missing=True))
    return normalized


def _command_scope_kind(tokens: list[str], command_index: int | None) -> str:
    if command_index is None or command_index >= len(tokens):
        return "read"
    name = Path(tokens[command_index]).name.lower()
    if name in {"cp", "mkdir", "mv", "rm", "tee", "touch", "truncate"}:
        return "write"
    rest = tokens[command_index + 1 :]
    if name == "sed" and any(t == "-i" or t.startswith("-i") for t in rest):
        return "write"
    if name != "git":
        return "read"
    subcommand = next(
        (t.lower() for t in rest if t not in _CONTROL_TOKENS and t != "--" and not t.startswith("-")), ""
    )
    return "write" if subcommand in {"checkout", "restore", "revert", "rm"} else "read"


def _extract_command_tool_paths(command: str | None, *, base_path: str | None) -> tuple[str, list[str]]:
    if not isinstance(command, str) or not command:
        return "read", []
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "read", []

    command_index: int | None = None
    for i, tok in enumerate(tokens):
        if tok in _CONTROL_TOKENS:
            break
        if _ENV_ASSIGNMENT_RE.match(tok):
            continue
        command_index = i
        break
    if command_index is None:
        return "read", []

    is_rg = Path(tokens[command_index]).name.lower() == "rg"
    saw_rg_pattern = False
    candidate_tokens: list[str] = []
    for tok in tokens[command_index + 1 :]:
        if tok in _CONTROL_TOKENS:
            break
        if tok.startswith("-"):
            continue
        if is_rg and not saw_rg_pattern:
            saw_rg_pattern = True
            continue
        candidate_tokens.append(tok)

    normalized: list[str] = []
    for tok in candidate_tokens:
        _append_unique_path(normalized, _normalize_tool_scope_path(tok, base_path=base_path, allow_missing=False))
    return _command_scope_kind(tokens, command_index), normalized


def _extract_apply_patch_paths(tool_input: dict[str, Any] | None, *, base_path: str | None) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    payload = tool_input.get("input")
    if not isinstance(payload, str) or "*** Begin Patch" not in payload:
        return []
    paths: list[str] = []
    for line in payload.splitlines():
        m = _PATCH_HEADER_RE.match(line) or _PATCH_MOVE_RE.match(line)
        if m:
            _append_unique_path(paths, _normalize_tool_scope_path(m.group(1), base_path=base_path, allow_missing=True))
    return paths


def extract_tool_scope_paths(
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    *,
    base_path: str | None,
) -> tuple[list[str], list[str]]:
    """Derive normalized read/write scope paths from a tool invocation."""
    normalized_tool = (tool_name or "").strip().lower()
    resolved_base = _tool_base_path(tool_input, base_path)
    explicit = _extract_explicit_tool_paths(tool_input, base_path=resolved_base)
    patch = _extract_apply_patch_paths(tool_input, base_path=resolved_base)
    cmd_kind, cmd_paths = _extract_command_tool_paths(_tool_command(tool_input), base_path=resolved_base)

    if "read" in normalized_tool or normalized_tool == "view_image":
        return merge_scope_paths(explicit), []
    if "write" in normalized_tool or "edit" in normalized_tool or normalized_tool == "apply_patch":
        return [], merge_scope_paths(explicit, patch)
    if normalized_tool in {"bash", "exec_command"}:
        if cmd_kind == "write":
            return [], merge_scope_paths(cmd_paths)
        return merge_scope_paths(cmd_paths), []
    return [], []


def resolve_scope_base_path(metadata: dict[str, Any] | None, cwd: str | None) -> str | None:
    """Resolve the best repo base path for scope normalization."""
    payload = metadata if isinstance(metadata, dict) else {}
    for key in ("repo_root", "cwd"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
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
    if declared_scope_paths:
        derived = "declared"
    elif observed_write_paths:
        derived = "observed_write"
    elif observed_read_paths:
        derived = "observed_read"
    else:
        derived = "unknown"
    if existing in _SCOPE_CONFIDENCE_RANK and _SCOPE_CONFIDENCE_RANK[existing] > _SCOPE_CONFIDENCE_RANK[derived]:
        return existing
    return derived


def _merge_scope_field(existing: list[str] | None, normalized: list[str]) -> list[str]:
    """Merge normalized paths into an existing field; initialize to empty list if absent."""
    if normalized:
        return merge_scope_paths(existing, normalized)
    return existing if existing is not None else []


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
    norm_declared = normalize_scope_paths(declared_scope_paths, base_path)
    norm_reads = normalize_scope_paths(observed_read_paths, base_path)
    norm_writes = normalize_scope_paths(observed_write_paths, base_path)

    if norm_declared:
        session.declared_scope_paths = norm_declared
    elif session.declared_scope_paths is None:
        session.declared_scope_paths = []

    session.observed_read_paths = _merge_scope_field(session.observed_read_paths, norm_reads)
    session.observed_write_paths = _merge_scope_field(session.observed_write_paths, norm_writes)

    session.scope_confidence = resolve_scope_confidence(
        scope_confidence,
        session.declared_scope_paths,
        session.observed_write_paths,
        session.observed_read_paths,
        session.scope_confidence,
    )
