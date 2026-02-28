"""Cross-project file-access permission hook for the tool handler.

Enforces that sessions operating under one project cannot read/write/exec
into another project's directory unless that project's permission tier
allows it.

Enforcement matrix:
    off  → DENY all (read_file, write_file, bash)
    read → ALLOW read_file, DENY write_file, DENY bash
    write/yolo → ALLOW all
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.tools.base import PreToolUseHook, ToolCall, ToolDecision

logger = logging.getLogger(__name__)


async def _resolve_tier(proj_id: str) -> str | None:
    """Return the permission tier for *proj_id*, using the cache when possible."""
    from app.services.project_permission_service import (
        _get_cached_tier,
        get_project_permission,
    )

    tier = await _get_cached_tier(proj_id)
    if tier is not None:
        return tier

    from app.db import async_session

    async with async_session() as db:
        perm = await get_project_permission(db, proj_id)
    return perm.permission_tier if perm else None


def _find_target_project(resolved_path: str, known_roots: dict[str, str]) -> str | None:
    """Return the project ID whose root contains *resolved_path*, or None."""
    for proj_id, root in known_roots.items():
        if resolved_path.startswith(root):
            return proj_id
    return None


async def _check_file_tool(
    tool_call: ToolCall,
    session_project_id: str,
    known_roots: dict[str, str],
) -> ToolDecision:
    """Permission gate for read_file / write_file cross-project access."""
    path = tool_call.input.get("path", "")
    if not path:
        return ToolDecision.ALLOW

    resolved = str(Path(path).resolve())
    target_project = _find_target_project(resolved, known_roots)

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

    for proj_id, root in known_roots.items():
        if proj_id == session_project_id or root not in command:
            continue

        tier = await _resolve_tier(proj_id)
        if tier in (None, "off", "read"):
            logger.info(
                "Cross-project DENY: bash referencing %s (target=%s, tier=%s). "
                "Use read_file/write_file for enforced cross-project access.",
                root, proj_id, tier,
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
