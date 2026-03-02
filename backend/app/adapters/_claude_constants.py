"""Shared constants for Claude adapter modules."""

# Thinking level → SDK effort mapping for Claude
THINKING_LEVEL_TO_EFFORT: dict[str, str | None] = {
    "minimal": None,       # Disabled
    "low": "low",
    "medium": "medium",
    "high": "high",
    "ultrathink": "max",
}

# Tool categories for permission handling
READ_TOOLS = {"read_file", "search_code", "list_files", "get_project_structure"}
WRITE_TOOLS = {"write_file", "edit_file", "delete_file", "create_directory"}

# CLI-builtin tools to expose by default (MCP tools are separate)
DEFAULT_ALLOWED_CLI_TOOLS = ["Read", "Write", "Bash", "Edit", "Glob", "Grep"]

# CLI builtins that are also registered as MCP tools (use lowercase names from tool defs)
_CLI_BUILTIN_TOOL_NAMES = frozenset({"bash", "read_file", "write_file"})

MCP_SERVER_NAME = "agent-hub"


def build_allowed_tools(
    custom_tools: list[dict[str, object]] | None = None,
    mcp_server_name: str = MCP_SERVER_NAME,
) -> list[str]:
    """Build the complete allowed_tools list including MCP tool names.

    Starts with CLI builtins, then appends mcp__<server>__<name> for each
    custom tool that will be exposed via MCP.
    """
    allowed = list(DEFAULT_ALLOWED_CLI_TOOLS)
    if custom_tools:
        for t in custom_tools:
            name = t.get("name", "")
            if name and name not in _CLI_BUILTIN_TOOL_NAMES:
                allowed.append(f"mcp__{mcp_server_name}__{name}")
    return allowed
