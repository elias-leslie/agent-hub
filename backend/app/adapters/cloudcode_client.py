"""Shared CloudCode PA HTTP client.

Extracted from gemini_cloudcode.py to be shared by both
GeminiCloudCodeAdapter (gemini_cloudcode.py) and
CloudCodeClaudeAdapter (cloudcode_claude.py).

Re-exports CloudCodeClient and shared helper functions from
gemini_cloudcode.py for convenience. This module serves as the
canonical import point for CloudCode client functionality.
"""

from __future__ import annotations

# Re-export from gemini_cloudcode (where the implementation lives)
from app.adapters.gemini_cloudcode import (
    CloudCodeClient,
    build_cloudcode_tools,
    convert_messages_for_cloudcode,
    parse_cloudcode_response,
)

__all__ = [
    "CloudCodeClient",
    "build_cloudcode_tools",
    "convert_messages_for_cloudcode",
    "parse_cloudcode_response",
]
