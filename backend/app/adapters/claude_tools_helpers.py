"""Helper functions for claude_tools.py — permission checking and SDK option construction."""

import logging
from typing import Any

from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)

# Tools already built into Claude Code CLI — skip when building MCP server
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})

_MCP_RACE_PATCHED = False


def _patch_sdk_mcp_race_condition() -> None:
    """Patch SDK race condition where MCP control response writes fail during shutdown.

    The SDK spawns _handle_control_request as a background task (start_soon)
    but close() can cancel the task group before the response is written back,
    causing CLIConnectionError. This patch catches that specific error.
    """
    global _MCP_RACE_PATCHED  # noqa: PLW0603
    if _MCP_RACE_PATCHED:
        return
    _MCP_RACE_PATCHED = True

    try:
        from claude_agent_sdk._errors import CLIConnectionError
        from claude_agent_sdk._internal.query import Query

        original = Query._handle_control_request

        async def _safe_handle_control_request(self: Any, request: Any) -> None:
            try:
                await original(self, request)
            except CLIConnectionError:
                logger.debug("MCP control response write failed (transport closed during shutdown)")
            except Exception:
                logger.debug("MCP control request error during shutdown", exc_info=True)

        Query._handle_control_request = _safe_handle_control_request  # type: ignore[assignment]
        logger.info("Patched SDK MCP race condition in Query._handle_control_request")
    except Exception:
        logger.warning("Failed to patch SDK MCP race condition", exc_info=True)


def _build_can_use_tool(checker: Any) -> Any:
    """Build a can_use_tool callback mapping PermissionChecker decisions to SDK types."""
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )

    from app.services.tools.base import ToolCall, ToolDecision

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        tool_call = ToolCall(id="", name=tool_name, input=tool_input)
        decision = await checker.check(tool_call)
        if decision == ToolDecision.ALLOW:
            return PermissionResultAllow()
        elif decision == ToolDecision.DENY:
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' denied by permission config"
            )
        else:  # ASK — deny in autonomous mode (no user to confirm)
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' requires confirmation (autonomous mode)"
            )

    return can_use_tool


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools.

    Registers non-CLI-builtin tools as MCP tools backed by DirectToolExecutor.
    Returns None if no custom tools to register.
    """
    from claude_agent_sdk import create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    from app.services.tools.direct_executor_core import DirectToolExecutor

    custom_tools = [t for t in tools if t["name"] not in _CLI_BUILTIN_TOOLS]
    if not custom_tools:
        return None

    _patch_sdk_mcp_race_condition()

    executor = DirectToolExecutor(working_dir, project_id=project_id)
    mcp_tools = []
    for t in custom_tools:
        tool_name = t["name"]

        async def handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            try:
                result = await executor.dispatch(_name, args)
                return {"content": [{"type": "text", "text": result}]}
            except Exception as e:
                logger.exception("MCP handler error: tool=%s", _name)
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(handler))

    return create_sdk_mcp_server("agent-hub-tools", tools=mcp_tools)


def _build_sdk_options(
    model: str,
    model_map: dict[str, str],
    working_dir: str | None,
    cli_path: str,
    yolo_mode: bool,
    permission_checker: Any | None,
    resume_session_id: str | None,
    tools: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
) -> tuple[Any, bool]:
    """Build ClaudeAgentOptions; return (options, use_streaming_prompt)."""
    from claude_agent_sdk import ClaudeAgentOptions

    sdk_model = model_map.get(model, model)
    sdk_opts: dict[str, Any] = {
        "cwd": working_dir or ".",
        "cli_path": cli_path,
        "model": sdk_model,
        "env": build_venv_env_overlay(working_dir or "."),
    }

    use_streaming_prompt = False
    if yolo_mode:
        sdk_opts["permission_mode"] = "bypassPermissions"
    elif permission_checker:
        sdk_opts["can_use_tool"] = _build_can_use_tool(permission_checker)
        use_streaming_prompt = True  # can_use_tool requires streaming mode

    if resume_session_id:
        sdk_opts["resume"] = resume_session_id
        logger.info(f"Claude SDK resuming session: {resume_session_id}")

    if tools:
        mcp_server = _build_mcp_server(tools, working_dir, project_id)
        if mcp_server:
            sdk_opts["mcp_servers"] = {"agent-hub": mcp_server}

    return ClaudeAgentOptions(**sdk_opts), use_streaming_prompt
