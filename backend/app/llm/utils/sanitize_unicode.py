"""Surrogate-sanitization helper (port of pi-mono ``utils/sanitize-unicode.ts``).

Python ``str`` stores code points, not UTF-16 code units, so unpaired
surrogates only appear when a producer hand-rolls them with ``chr(0xD83D)``
etc. They fail UTF-8 encoding (the Anthropic SDK's JSON serializer), so we
strip them here before the message reaches the wire.
"""

from __future__ import annotations

import re

# Matches a high surrogate not followed by a low surrogate, OR a low
# surrogate not preceded by a high surrogate.
_UNPAIRED_SURROGATE_RE = re.compile(
    r"[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]"
)


def sanitize_surrogates(text: str) -> str:
    """Remove unpaired Unicode surrogate code units. Valid astral pairs are kept."""
    if not text:
        return text
    return _UNPAIRED_SURROGATE_RE.sub("", text)


__all__ = ["sanitize_surrogates"]
