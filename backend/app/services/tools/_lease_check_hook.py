"""Lease-check hook for the tool handler.

Bridges Agent Hub's DirectToolExecutor write paths into SummitFlow's
advisory edit leases (`st lease --check`), the same check the harness edit
hook runs: it claims the path for this agent and reports overlap.

    write_file / edit_file → `st lease --check <path>`:
        exit 0 + "WARNING: ..." (another agent's lease) → ALLOW, warning
                                 prepended to the tool output as context
        exit 2 + "BLOCKED: ..." (live acceptance/deploy) → DENY
    everything else        → ALLOW

The check runs with cwd=project_root and a short timeout.
AGENT_HUB_SESSION_ID and AGENT_HUB_AGENT_SLUG flow through inherited env so
`st lease` can identify the agent.

Fail-open: missing `st` binary, missing project root, subprocess error, or
timeout all return ALLOW. Leases are coordination, not a security boundary.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from app.services.tools.base import PreToolUseHook, ToolCall, ToolDecision
from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)

_LEASE_CHECK_TIMEOUT_SECONDS = 4.0


def _resolve_path(path: str, project_root: Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return (project_root / target).resolve(strict=False)


async def _run_lease_check(
    resolved_path: Path, project_root: Path, tool_call: ToolCall
) -> ToolDecision:
    st_binary = shutil.which("st")
    if st_binary is None:
        return ToolDecision.ALLOW

    try:
        proc = await create_process(
            st_binary,
            "lease",
            "--check",
            str(resolved_path),
            working_dir=project_root,
        )
    except (OSError, ValueError) as exc:
        logger.warning("lease check spawn failed for %s: %s", resolved_path, exc)
        return ToolDecision.ALLOW

    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_LEASE_CHECK_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        logger.warning("lease check timed out for %s", resolved_path)
        return ToolDecision.ALLOW

    message = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode == 2:
        logger.info("Lease DENY: %s (%s)", resolved_path, message or "live acceptance/deploy")
        return ToolDecision.DENY
    if message.startswith("WARNING:"):
        tool_call.notes.append(message)
    return ToolDecision.ALLOW


def create_lease_check_hook(project_id: str) -> PreToolUseHook:
    """Return a pre-hook that warns on another agent's lease and blocks under a live op."""
    from app.services.tools._executor_roots import KNOWN_ROOTS

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            if tool_call.name not in ("write_file", "edit_file"):
                return ToolDecision.ALLOW

            raw_path = (
                tool_call.input.get("path")
                or tool_call.input.get("file_path")
                or ""
            )
            if not raw_path:
                return ToolDecision.ALLOW

            root = KNOWN_ROOTS.get(project_id)
            if not root:
                return ToolDecision.ALLOW
            project_root = Path(root)

            resolved = _resolve_path(str(raw_path), project_root)
            return await _run_lease_check(resolved, project_root, tool_call)
        except Exception as exc:
            logger.warning(
                "Lease hook error for %s on %s: %s — allowing",
                tool_call.name, project_id, exc,
            )
            return ToolDecision.ALLOW

    return _hook
