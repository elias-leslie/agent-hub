"""Cross-project file-access permission hook for the tool handler.

Enforces that sessions operating under one project cannot read/write/exec
into another project's directory unless that project's permission tier
allows it.

Enforcement matrix:
    off  → DENY all (read_file, write_file, bash)
    read → ALLOW read_file, DENY write_file, DENY bash
    full → ALLOW all
"""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path

from app.services.tools.base import PreToolUseHook, ToolCall, ToolDecision

logger = logging.getLogger(__name__)


async def _resolve_tier(proj_id: str) -> str | None:
    """Return the permission tier for *proj_id*, using the cache when possible."""
    from app.models.project_permission import normalize_permission_tier
    from app.services.project_permission_service import (
        _get_cached_tier,
        get_project_permission,
    )

    tier = await _get_cached_tier(proj_id)
    if tier is not None:
        return normalize_permission_tier(tier)

    from app.db import async_session

    async with async_session() as db:
        perm = await get_project_permission(db, proj_id)
        return normalize_permission_tier(perm.permission_tier) if perm else None


def _path_within_root(resolved_path: str, root: str) -> bool:
    """Return True when *resolved_path* is inside *root*."""
    try:
        Path(resolved_path).relative_to(Path(root))
        return True
    except ValueError:
        return False


def _find_target_project(resolved_path: str, known_roots: dict[str, str]) -> str | None:
    """Return the project ID whose root contains *resolved_path*, or None."""
    roots_by_specificity = sorted(
        ((proj_id, root) for proj_id, root in known_roots.items() if root),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for proj_id, root in roots_by_specificity:
        if _path_within_root(resolved_path, root):
            return proj_id
    return None


def _resolve_checkout_owner_root(path: Path) -> Path | None:
    """Return canonical repo root when *path* is inside a linked git checkout."""
    from app.services.tools.project_env import detect_repo_root

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


def _infer_target_project(path: Path, known_roots: dict[str, str]) -> str | None:
    """Infer the owning project for a resolved path."""
    if owner_root := _resolve_checkout_owner_root(path):
        target_project = _find_target_project(str(owner_root), known_roots)
        if target_project:
            return target_project
    resolved_path = str(path.resolve(strict=False))
    return _find_target_project(resolved_path, known_roots)


def _extract_absolute_paths(command: str) -> list[Path]:
    """Extract likely absolute paths from a bash command string."""
    candidates: list[str] = []
    try:
        for token in shlex.split(command):
            stripped = token.strip("\"'")
            if stripped.startswith("/"):
                candidates.append(stripped)
                continue
            if "=/" in stripped:
                _, value = stripped.split("=/", 1)
                candidates.append(f"/{value}")
    except ValueError:
        candidates.extend(re.findall(r"(?<![A-Za-z0-9_.-])(/[^\s;&|]+)", command))

    return [Path(candidate.rstrip(");,")) for candidate in candidates if candidate.startswith("/")]


async def _check_file_tool(
    tool_call: ToolCall,
    session_project_id: str,
    known_roots: dict[str, str],
) -> ToolDecision:
    """Permission gate for read_file / write_file cross-project access."""
    path = tool_call.input.get("path", "")
    if not path:
        return ToolDecision.ALLOW

    target_project = _infer_target_project(Path(path), known_roots)

    if target_project is None or target_project == session_project_id:
        return ToolDecision.ALLOW

    tier = await _resolve_tier(target_project)
    if tier is None or tier == "off":
        logger.info(
            "Cross-project DENY: %s on %s (target=%s, tier=%s)",
            tool_call.name, path, target_project, tier,
        )
        return ToolDecision.DENY

    if tool_call.name == "write_file" and tier == "read":
        logger.info(
            "Cross-project DENY: write_file on %s (target=%s, tier=read)",
            path, target_project,
        )
        return ToolDecision.DENY

    return ToolDecision.ALLOW


async def _check_bash_tool(
    tool_call: ToolCall,
    session_project_id: str,
    known_roots: dict[str, str],
) -> ToolDecision:
    """Permission gate for bash cross-project path references."""
    command = tool_call.input.get("command", "")
    if not command:
        return ToolDecision.ALLOW

    checked_projects: set[str] = set()
    for candidate in _extract_absolute_paths(command):
        target_project = _infer_target_project(candidate, known_roots)
        if target_project is None or target_project == session_project_id or target_project in checked_projects:
            continue
        checked_projects.add(target_project)

        tier = await _resolve_tier(target_project)
        if tier in (None, "off", "read"):
            logger.info(
                "Cross-project DENY: bash referencing %s (target=%s, tier=%s). "
                "Use read_file/write_file for enforced cross-project access.",
                candidate, target_project, tier,
            )
            return ToolDecision.DENY

    return ToolDecision.ALLOW


def create_cross_project_permission_hook(session_project_id: str) -> PreToolUseHook:
    """Return a pre-hook that enforces cross-project file access permissions.

    When a session runs under one project (e.g. persona-sandbox) but accesses
    files in another project's directory, this hook checks the *target*
    project's permission tier and enforces read/write/deny accordingly.

    For bash: scans the command string for absolute paths matching known
    project roots. Not bulletproof against adversarial evasion, but catches
    all non-adversarial cross-project access (the intended threat model).
    """
    from app.services.tools.direct_executor_core import KNOWN_ROOTS

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            if tool_call.name in ("read_file", "write_file"):
                return await _check_file_tool(tool_call, session_project_id, KNOWN_ROOTS)
            if tool_call.name == "bash":
                return await _check_bash_tool(tool_call, session_project_id, KNOWN_ROOTS)
            return ToolDecision.ALLOW
        except Exception as e:
            logger.error(
                "Cross-project hook error for %s: %s — denying",
                tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook
