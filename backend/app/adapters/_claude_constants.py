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
