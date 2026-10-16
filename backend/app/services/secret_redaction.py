"""High-confidence secret floor applied before anything is stored or embedded.

Only token shapes that are near-certain credentials: a false positive costs a
few characters of history, a miss stores a live key and sends it to the
embedding API. Patterns are linear (bounded classes, no nested quantifiers).
This module imports only the standard library because models import it.
"""

from __future__ import annotations

import re
from typing import Any

_KEY_BODY = r"[A-Za-z0-9+/=\s\\:,.\-]"

# Where a token may start: not right after a letter, digit or underscore, except
# after an escape that leaves one there: ``\\n``, ``\\x22``, ``\\u0022``, ``\\042``
# in JSON or quoted text, ``%3D`` (or ``%253D``) in a URL. A token inside a longer
# identifier stays. A terminal color code before a token (``grep --color``,
# raw or JSON-escaped) is consumed as ``esc`` and put back in the replacement.
_START = (
    r"(?:(?<![A-Za-z0-9_])|(?<=\\[nrtfv0])|(?<=\\[0-7]{3})|(?<=\\x[0-9A-Fa-f]{2})"
    r"|(?<=\\u[0-9A-Fa-f]{4})|(?<=\\U[0-9A-Fa-f]{8})|(?<=%[0-9A-Fa-f]{2})|(?<=%25[0-9A-Fa-f]{2})"
    r"|(?P<esc>(?:\x1b|\\u001[bB]|\\x1[bB]|\\033|\\e)\[[0-?]{0,20}[ -/]{0,2}[@-~]))"
)

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    # A whole PEM block when its END line is present, else the header and the
    # base64 lines that follow it (also as escaped ``\\n`` inside JSON text).
    # A bare header (prose or code naming it) is not key material. The body
    # scan is bounded so many headers without an END stay linear.
    "private_key": re.compile(
        r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----"
        rf"(?:{_KEY_BODY}{{0,8192}}?-----END [A-Z0-9 ]{{0,40}}PRIVATE KEY(?: BLOCK)?-----"
        r"|(?:(?:\s|\\[nr])+[A-Za-z0-9+/=]{40,})+)"
    ),
    "aws_access_key": re.compile(rf"{_START}AKIA[0-9A-Z]{{16}}(?![0-9A-Z])"),
    "github_token": re.compile(
        rf"{_START}(?:gh[pousr]_[A-Za-z0-9]{{36,255}}|github_pat_[A-Za-z0-9_]{{22,255}})"
    ),
    "gitlab_token": re.compile(rf"{_START}glpat-[A-Za-z0-9_\-]{{20,255}}"),
    "slack_token": re.compile(rf"{_START}xox[abposr]-[A-Za-z0-9\-]{{10,255}}"),
    "anthropic_key": re.compile(rf"{_START}sk-ant-[A-Za-z0-9_\-]{{20,255}}"),
    "stripe_live_key": re.compile(rf"{_START}[rs]k_live_[A-Za-z0-9]{{20,255}}"),
}


def redact_secrets(text: str) -> tuple[str, dict[str, int]]:
    """Replace each secret match with ``[REDACTED:<kind>]``; return counts per kind."""
    counts: dict[str, int] = {}
    for kind, pattern in SECRET_PATTERNS.items():
        tag = f"[REDACTED:{kind}]"
        text, hits = pattern.subn(lambda match, tag=tag: (match.groupdict().get("esc") or "") + tag, text)
        if hits:
            counts[kind] = hits
    return text, counts


def redact_text(text: str | None) -> str | None:
    """``redact_secrets`` for optional text columns, without the counts."""
    return text if not text else redact_secrets(text)[0]


def redact_value(value: Any) -> Any:
    """Redact every string inside a JSON-like value (dict keys are left alone).

    Returns the original object when nothing matched, so unchanged JSON
    columns are not marked dirty.
    """
    if isinstance(value, str):
        redacted, counts = redact_secrets(value)
        return redacted if counts else value
    if isinstance(value, list):
        items = [redact_value(item) for item in value]
        return value if all(new is old for new, old in zip(items, value, strict=True)) else items
    if isinstance(value, dict):
        redacted = {key: redact_value(item) for key, item in value.items()}
        return value if all(redacted[key] is item for key, item in value.items()) else redacted
    return value
