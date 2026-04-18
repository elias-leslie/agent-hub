"""Checkout write-boundary permission hook for the tool handler.

Enforces that sessions operating in a checkout cannot write files outside
their assigned working directory. Reads are unrestricted — the boundary
only applies to write operations.

Enforcement:
    write_file / edit → DENY if resolved path is not under working_dir
                        and not in the write allowlist (/tmp/, ~/.claude/)
    read_file         → ALLOW always
    bash              → ALLOW always (impractical to parse reliably)
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.tools.base import PreToolUseHook, ToolCall, ToolDecision

logger = logging.getLogger(__name__)

# Directories where writes are always allowed regardless of checkout boundary.
_WRITE_ALLOWLIST: tuple[Path, ...] = (
    Path("/tmp"),
    Path.home() / ".claude",
)


def _is_write_allowed(resolved: Path, boundary: Path) -> bool:
    """Check if a write to *resolved* is allowed given the checkout *boundary*."""
    if resolved.is_relative_to(boundary):
        return True
    return any(resolved.is_relative_to(allowed) for allowed in _WRITE_ALLOWLIST)


def _resolve_target_path(path: str, boundary: Path) -> Path:
    """Resolve a write target relative to the checkout boundary when needed."""
    target = Path(path)
    if target.is_absolute():
        return target.resolve()
    return (boundary / target).resolve()


def create_checkout_boundary_hook(working_dir: str) -> PreToolUseHook:
    """Return a pre-hook that blocks writes outside the checkout boundary.

    Only write_file operations are gated. read_file and bash are always
    allowed — bash is impractical to parse reliably (same limitation as
    the cross-project hook).

    Fail-closed: any exception during checking results in DENY.
    """
    boundary = Path(working_dir).resolve()

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            if tool_call.name == "read_file":
                return ToolDecision.ALLOW

            if tool_call.name == "write_file":
                path = tool_call.input.get("path") or tool_call.input.get("file_path") or ""
                if not path:
                    return ToolDecision.ALLOW
                resolved = _resolve_target_path(str(path), boundary)
                if not _is_write_allowed(resolved, boundary):
                    logger.info(
                        "Checkout boundary DENY: write_file on %s (boundary=%s)",
                        path, boundary,
                    )
                    return ToolDecision.DENY
                return ToolDecision.ALLOW

            # bash, read_file, and all other tools — unrestricted
            return ToolDecision.ALLOW
        except Exception as e:
            logger.error(
                "Checkout boundary hook error for %s: %s — denying",
                tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook
