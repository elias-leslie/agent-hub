"""Constants shared across tool definition modules."""

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
