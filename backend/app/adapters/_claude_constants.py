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
DEFAULT_ALLOWED_CLI_TOOLS = ["Read", "Write", "Bash", "Edit"]
DEFAULT_DISALLOWED_CLI_TOOLS = ["WebFetch", "WebSearch", "Agent"]

# CLI builtins that are also registered as MCP tools (use lowercase names from tool defs)
_CLI_BUILTIN_TOOL_NAMES = frozenset({"bash", "read_file", "write_file"})
_CLI_TOOL_NAME_MAP: dict[str, list[str]] = {
    "bash": ["Bash"],
    "read_file": ["Read"],
    # Keep both provider-native write surfaces when write_file is exposed.
    "write_file": ["Write", "Edit"],
}

MCP_SERVER_NAME = "agent-hub"
MCP_TOOL_PREFIX = f"mcp__{MCP_SERVER_NAME}__"


def build_mcp_tool_name(
    tool_name: str,
    *,
    mcp_server_name: str = MCP_SERVER_NAME,
) -> str:
    """Return the Claude MCP-qualified tool name for a bare tool."""
    return f"mcp__{mcp_server_name}__{tool_name}"


def build_allowed_tools(
    custom_tools: list[dict[str, object]] | None = None,
    mcp_server_name: str = MCP_SERVER_NAME,
) -> list[str]:
    """Build the complete allowed_tools list including MCP tool names.

    When a tool list is provided, expose only the CLI builtins represented in
    that list, then append mcp__<server>__<name> for each non-builtin tool.
    This keeps Claude's native builtin surface aligned with the provisioned
    Agent Hub tool surface.
    """
    if not custom_tools:
        return list(DEFAULT_ALLOWED_CLI_TOOLS)

    allowed: list[str] = []
    seen: set[str] = set()
    for t in custom_tools:
        name = str(t.get("name", "") or "")
        if not name:
            continue
        builtin_names = _CLI_TOOL_NAME_MAP.get(name)
        if builtin_names is not None:
            for builtin_name in builtin_names:
                if builtin_name not in seen:
                    allowed.append(builtin_name)
                    seen.add(builtin_name)
            continue
        qualified = build_mcp_tool_name(name, mcp_server_name=mcp_server_name)
        if qualified not in seen:
            allowed.append(qualified)
            seen.add(qualified)
    return allowed
