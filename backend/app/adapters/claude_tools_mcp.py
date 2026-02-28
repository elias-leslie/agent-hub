"""MCP server helpers for Claude adapter — race-condition patch and server construction."""

import logging
from typing import Any

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
    global _MCP_RACE_PATCHED
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


def build_mcp_server(
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
