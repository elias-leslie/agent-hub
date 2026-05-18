"""Lease-check permission hook for the tool handler.

Bridges Agent Hub's DirectToolExecutor write paths into SummitFlow's
file-lease coordination primitive (`st lease`). When another agent holds
a lease covering the target path, the hook denies the write so two
agents can't race on the same file.

Enforcement:
    write_file / edit_file → DENY when `st lease --check <path>` exits 2
    bash                   → ALLOW always (opaque commands; impractical
                             to scan reliably)
    everything else        → ALLOW

The lease check runs `st lease --check <resolved_path>` as a subprocess
with cwd=project_root and a short timeout. AGENT_HUB_SESSION_ID and
AGENT_HUB_AGENT_SLUG flow through inherited env so `st lease` can
identify the agent and refresh the holder's heartbeat for matching
same-agent leases.

Fail-open: missing `st` binary, missing project root, subprocess error,
or timeout all return ALLOW. The lease is a coordination convenience,
not a security boundary — failing closed would block all writes when
SummitFlow is offline.
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


async def _run_lease_check(resolved_path: Path, project_root: Path) -> ToolDecision:
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

    if proc.returncode == 2:
        message = stderr.decode("utf-8", errors="replace").strip()
        logger.info("Lease DENY: %s (%s)", resolved_path, message or "held by another agent")
        return ToolDecision.DENY
    return ToolDecision.ALLOW


def create_lease_check_hook(project_id: str) -> PreToolUseHook:
    """Return a pre-hook that blocks writes covered by another agent's lease."""
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
            return await _run_lease_check(resolved, project_root)
        except Exception as exc:
            logger.warning(
                "Lease hook error for %s on %s: %s — allowing",
                tool_call.name, project_id, exc,
            )
            return ToolDecision.ALLOW

    return _hook
