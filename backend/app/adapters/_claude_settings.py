"""Settings-based write boundary enforcement for Claude SDK subprocess.

The Claude SDK subprocess does NOT invoke ``can_use_tool`` callbacks for
built-in tools (Write, Edit, Bash, Read).  Instead, we use two
complementary mechanisms that are evaluated **inside** the subprocess:

1. **``settings`` parameter** — a JSON dict with ``permissions.allow``
   patterns restricting Write/Edit to the worktree path.  This is the
   primary enforcement.

2. **``PreToolUse`` hook** — a Python callback registered via the SDK
   ``hooks`` parameter.  This is defense-in-depth that catches edge
   cases the settings patterns might miss (path normalization tricks).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, cast

from app.services.persona_policy import (
    command_hits_persona_git_publish_policy,
    get_persona_git_publish_block_reason,
)
from app.services.tools._sensitive_content import scan_runtime_sensitive_content

logger = logging.getLogger(__name__)

# Directories where writes are always allowed regardless of worktree boundary.
_WRITE_ALLOWLIST: tuple[Path, ...] = (
    Path("/tmp"),
    Path.home() / ".claude",
)
def build_boundary_settings(working_dir: str) -> dict[str, Any]:
    """Build a Claude Code settings dict restricting writes to *working_dir*.

    The returned dict follows Claude Code's settings.json schema.
    ``permissions.allow`` lists tool-level allow patterns; ``defaultMode``
    is set to ``"acceptEdits"`` so allowed writes proceed without prompts
    while disallowed writes are blocked.
    """
    resolved = str(Path(working_dir).resolve())
    home_claude = str(Path.home() / ".claude")

    return {
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                # Read: unrestricted
                "Read(*)",
                # Write / Edit: scoped to worktree + allowlist
                "Write(./**)",
                "Edit(./**)",
                f"Write({resolved}/**)",
                f"Edit({resolved}/**)",
                # Allowlisted write destinations
                "Write(/tmp/**)",
                "Edit(/tmp/**)",
                f"Write({home_claude}/**)",
                f"Edit({home_claude}/**)",
                # Bash: unrestricted (impractical to parse)
                "Bash(*)",
                # MCP tools: unrestricted (custom tools already gated by DirectToolHandler)
                "mcp__*(*)",
            ],
        },
    }


def write_boundary_settings(working_dir: str) -> str:
    """Write boundary settings to a temp file and return the path.

    The Claude SDK ``settings`` parameter accepts a JSON string or file
    path.  We write to a file to avoid shell-escaping issues with long
    JSON strings.
    """
    settings = build_boundary_settings(working_dir)
    fd, path = tempfile.mkstemp(prefix="claude_boundary_", suffix=".json")
    with open(fd, "w") as f:
        json.dump(settings, f)
    logger.debug("Wrote boundary settings to %s for working_dir=%s", path, working_dir)
    return path


def _deny_output(reason: str) -> Any:
    return cast(
        Any,
        {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        },
    )


def _extract_runtime_content(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Write":
        value = tool_input.get("content", "")
        return value if isinstance(value, str) else ""
    if tool_name == "Edit":
        value = tool_input.get("new_string") or tool_input.get("replacement") or ""
        return value if isinstance(value, str) else ""
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        if not isinstance(edits, list):
            return ""
        parts: list[str] = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            new_string = edit.get("new_string") or edit.get("replacement") or ""
            if isinstance(new_string, str):
                parts.append(new_string)
        return "\n".join(parts)
    return ""


def build_boundary_hook(working_dir: str, agent_slug: str | None = None) -> dict[str, list[Any]]:
    """Build SDK PreToolUse hook for write boundary enforcement.

    Returns a hooks dict suitable for ``ClaudeAgentOptions(hooks=...)``.
    The hook blocks Write/Edit/MultiEdit calls that target paths outside
    the worktree boundary (with an allowlist for /tmp and ~/.claude).
    """
    from claude_agent_sdk.types import HookContext, HookInput, HookJSONOutput, HookMatcher

    boundary = Path(working_dir).resolve()

    async def _check_write_boundary(
        input_data: HookInput,
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        tool_name = input_data.get("tool_name", "")
        if tool_name == "Bash" and agent_slug == "persona":
            tool_input = input_data.get("tool_input", {})
            command = tool_input.get("command", "")
            if isinstance(command, str) and command_hits_persona_git_publish_policy(command):
                logger.info("Boundary hook DENY: Bash workflow policy for persona (%s)", command)
                return _deny_output(get_persona_git_publish_block_reason())

        if tool_name not in ("Write", "Edit", "MultiEdit"):
            return {}

        tool_input = input_data.get("tool_input", {})
        path = tool_input.get("file_path") or tool_input.get("path") or ""
        if not path:
            return {}

        resolved = Path(path).resolve()
        if not resolved.is_relative_to(boundary) and not any(
            resolved.is_relative_to(a) for a in _WRITE_ALLOWLIST
        ):
            logger.info(
                "Boundary hook DENY: %s on %s (boundary=%s)", tool_name, path, boundary,
            )
            return _deny_output(f"Write blocked: {path} is outside worktree boundary {boundary}")

        content = _extract_runtime_content(tool_name, tool_input)
        block_reason = await scan_runtime_sensitive_content(
            str(resolved),
            content,
            repo_root=str(boundary),
            tool_name=tool_name,
        )
        if block_reason:
            logger.info("Boundary hook DENY: sensitive content in %s", path)
            return _deny_output(f"Write blocked: {block_reason}")

        return {}

    return {
        "PreToolUse": [
            HookMatcher(
                matcher="Write|Edit|MultiEdit|Bash",
                hooks=[_check_write_boundary],
            ),
        ],
    }
