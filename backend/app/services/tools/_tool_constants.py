"""Constants shared across tool definition modules."""

import shlex

# Default timeout for bash command execution (seconds)
DEFAULT_TIMEOUT: int = 120

# Default line limit for read_file tool
DEFAULT_READ_LIMIT: int = 2000

# Schema type literals
SCHEMA_TYPE_OBJECT = "object"
SCHEMA_TYPE_STRING = "string"
SCHEMA_TYPE_INTEGER = "integer"
SCHEMA_TYPE_BOOLEAN = "boolean"
SCHEMA_TYPE_ARRAY = "array"
SCHEMA_TYPE_NUMBER = "number"


def st_cmd(subcommand: str, project_id: str | None = None) -> str:
    """Build st CLI command with -P flag in correct position (before subcommand)."""
    if project_id:
        return f"st -P {shlex.quote(project_id)} {subcommand}"
    return f"st {subcommand}"
