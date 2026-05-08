"""Header constants for access control middleware.

Centralized header name definitions used across access control modules.
"""

# Required headers for client identification
CLIENT_ID_HEADER = "X-Client-Id"
REQUEST_SOURCE_HEADER = "X-Request-Source"
SOURCE_CLIENT_HEADER = "X-Source-Client"  # Identifies client type (st-cli, sdk, etc.)
TOOL_NAME_HEADER = "X-Tool-Name"  # Specific command/method (e.g., "st complete", "st agent")
SOURCE_PATH_HEADER = "X-Source-Path"  # Caller file path for debugging
