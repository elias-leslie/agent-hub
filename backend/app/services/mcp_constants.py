"""MCP naming constants used by transcript and benchmark fixtures."""

MCP_SERVER_NAME = "agent-hub"
MCP_TOOL_PREFIX = f"mcp__{MCP_SERVER_NAME}__"


def build_mcp_tool_name(
    tool_name: str,
    *,
    mcp_server_name: str = MCP_SERVER_NAME,
) -> str:
    """Return the MCP-qualified tool name for a bare tool."""
    return f"mcp__{mcp_server_name}__{tool_name}"
