"""Constants shared across tool definition modules."""

import shlex

# Default timeout for bash command execution (seconds)
DEFAULT_TIMEOUT: int | None = None

# Default line limit for read_file tool
DEFAULT_READ_LIMIT: int = 2000

# Read-only, stateless tools the tool loop may run concurrently when the model emits several in
# one turn. Everything else (bash, writes, edits, consults, state-changing tools) stays serial.
PARALLEL_SAFE_TOOLS: frozenset[str] = frozenset(
    {"read_file", "search_scratch_context", "search_web", "fetch_web_page"}
)

# Single-file writes the tool loop may run concurrently when the model emits several in one turn, as long as
# each targets a different file (each pays a sensitive-content scan, so they overlap). `MAX_PARALLEL_FILE_WRITES`
# bounds how many scans run at once.
PARALLEL_FILE_WRITE_TOOLS: frozenset[str] = frozenset({"write_file", "edit_file"})
MAX_PARALLEL_FILE_WRITES: int = 4

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
