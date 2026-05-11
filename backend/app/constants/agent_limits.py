"""Shared limits for agentic completions.

These exist because some loops physically need a number to iterate over. They
are headroom, not safety caps: pick high enough that no real agentic task hits
them, low enough that a genuine runaway loop eventually stops.

Do not add new "sensible defaults" here. If a provider treats a parameter as
optional, leave it unset and let the provider use its native default.
"""

from __future__ import annotations

# Default max tool-loop turns for adapters whose tool loop iterates a fixed
# range. Matches the request-schema default. ~5000 turns is far beyond any
# legitimate agentic task; this is a runaway guard, not a productivity cap.
DEFAULT_AGENTIC_MAX_TURNS = 5000
