"""CloudCode PA client for Gemini consumer OAuth (zero per-token cost).

Uses cloudcode-pa.googleapis.com instead of Vertex AI, matching how
Gemini CLI and other consumer tools access the API with a Google
subscription (Google One AI Pro / Gemini Code Assist).

The genai SDK's vertexai=True mode routes through Vertex AI which is a
pay-per-token service and returns 404 for consumer-only models.  This
module makes raw HTTP calls to the same endpoint that the Gemini CLI uses.

Implementation is split across internal submodules:
  _gemini_cloudcode_client.py    — CloudCodeClient HTTP class
  _gemini_cloudcode_transforms.py — message/tool/config conversion
  _gemini_cloudcode_ops.py       — complete/stream/tool-loop operations

This file re-exports the full public API so all existing import paths
continue to work unchanged.
"""

from __future__ import annotations

# Re-export everything that callers depend on from the submodules.
from app.adapters._gemini_cloudcode_client import (
    CloudCodeClient,
)
from app.adapters._gemini_cloudcode_ops import (
    cloudcode_complete,
    cloudcode_stream,
    cloudcode_tool_loop,
    parse_cloudcode_response,
)
from app.adapters._gemini_cloudcode_transforms import (
    build_cloudcode_tools,
    build_generation_config,
    convert_messages_for_cloudcode,
)

__all__ = [
    "CloudCodeClient",
    "build_cloudcode_tools",
    "build_generation_config",
    "cloudcode_complete",
    "cloudcode_stream",
    "cloudcode_tool_loop",
    "convert_messages_for_cloudcode",
    "parse_cloudcode_response",
]
