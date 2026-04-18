"""Permission-checking helpers for Claude adapter — tool name normalization and hook composition."""

from typing import Any

# SDK uses PascalCase for CLI builtins; permission hooks expect lowercase.
# Must match _SDK_TOOL_NAME_MAP in tool_handler.py.
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}


def normalize_tool_name(name: str) -> str:
    """Normalize SDK tool names for permission hooks.

    Handles two cases:
    1. MCP prefix: 'mcp__agent-hub__write_user_context' → 'write_user_context'
    2. SDK PascalCase builtins: 'Bash' → 'bash', 'Read' → 'read_file', etc.
    """
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return _SDK_TOOL_NAME_MAP.get(name, name)


def compose_permission_hooks(project_id: str | None) -> Any | None:
    """Build a composed PreToolUseHook from real runtime permission layers.

    Note: checkout boundary enforcement for the Claude SDK path is handled
    by settings-based enforcement (see ``_claude_settings.py``), not via
    ``can_use_tool``.  The DirectToolHandler path still uses the checkout
    boundary hook in ``tool_handler.py``.
    """
    from app.services.tools.base import PreToolUseHook
    from app.services.tools.tool_handler import (
        _compose_hooks,
        _create_cross_project_permission_hook,
        _create_project_permission_hook,
    )

    hooks: list[PreToolUseHook] = []
    if project_id:
        hooks.append(_create_project_permission_hook(project_id))
        hooks.append(_create_cross_project_permission_hook(project_id))

    if not hooks:
        return None
    return hooks[0] if len(hooks) == 1 else _compose_hooks(hooks)


def make_can_use_tool_callback(composed_hook: Any | None, agent_slug: str | None = None) -> Any:
    """Return an async can_use_tool callback for the given composed hook."""
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )

    from app.services.tools._executor_bash import get_persona_block_reason
    from app.services.tools.base import ToolCall, ToolDecision

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        normalized_name = normalize_tool_name(tool_name)
        if normalized_name == "bash":
            command = tool_input.get("command", "")
            if isinstance(command, str):
                persona_block_reason = get_persona_block_reason(command, agent_slug)
                if persona_block_reason:
                    return PermissionResultDeny(
                        message=f"Tool '{tool_name}' denied by workflow policy: {persona_block_reason}"
                    )

        if composed_hook is None:
            return PermissionResultAllow()

        tool_call = ToolCall(id="", name=normalized_name, input=tool_input)
        decision = await composed_hook(tool_call)

        if decision == ToolDecision.DENY:
            return PermissionResultDeny(message=f"Tool '{tool_name}' denied by permission policy")
        return PermissionResultAllow()

    return can_use_tool
