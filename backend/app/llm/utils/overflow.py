"""Context-overflow detection (port of pi-mono ``utils/overflow.ts``).

See the original module docstring for per-provider rationale; the regex
list below is copied verbatim.
"""

from __future__ import annotations

import re

from ..types import AssistantMessage

_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"prompt is too long", re.IGNORECASE),
    re.compile(r"request_too_large", re.IGNORECASE),
    re.compile(r"input is too long for requested model", re.IGNORECASE),
    re.compile(r"exceeds the context window", re.IGNORECASE),
    re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE),
    re.compile(r"maximum prompt length is \d+", re.IGNORECASE),
    re.compile(r"reduce the length of the messages", re.IGNORECASE),
    re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE),
    re.compile(r"input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)", re.IGNORECASE),
    re.compile(r"exceeds the limit of \d+", re.IGNORECASE),
    re.compile(r"exceeds the available context size", re.IGNORECASE),
    re.compile(r"greater than the context length", re.IGNORECASE),
    re.compile(r"context window exceeds limit", re.IGNORECASE),
    re.compile(r"exceeded model token limit", re.IGNORECASE),
    re.compile(r"too large for model with \d+ maximum context length", re.IGNORECASE),
    re.compile(r"model_context_window_exceeded", re.IGNORECASE),
    re.compile(r"prompt too long; exceeded (?:max )?context length", re.IGNORECASE),
    re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"token limit exceeded", re.IGNORECASE),
    re.compile(r"^4(?:00|13)\s*(?:status code)?\s*\(no body\)", re.IGNORECASE),
)


_NON_OVERFLOW_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(Throttling error|Service unavailable):", re.IGNORECASE),
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
)


def is_context_overflow(message: AssistantMessage, context_window: int | None = None) -> bool:
    """Return ``True`` if ``message`` indicates context-window overflow.

    Three detection modes:

    1. Error-based: ``stop_reason == "error"`` with an ``error_message``
       matching one of the per-provider patterns.
    2. Silent overflow (z.ai): ``stop_reason == "stop"`` but
       ``usage.input + usage.cache_read > context_window``.
    3. Length-stop overflow (Xiaomi MiMo): server truncates input to fit the
       window, leaving no room for output (``output == 0`` and input fills
       ≥99 % of the window).
    """

    if (
        message.stop_reason == "error"
        and message.error_message
        and not any(p.search(message.error_message) for p in _NON_OVERFLOW_PATTERNS)
        and any(p.search(message.error_message) for p in _OVERFLOW_PATTERNS)
    ):
        return True

    if context_window and message.stop_reason == "stop":
        input_tokens = message.usage.input + message.usage.cache_read
        if input_tokens > context_window:
            return True

    if context_window and message.stop_reason == "length" and message.usage.output == 0:
        input_tokens = message.usage.input + message.usage.cache_read
        if input_tokens >= context_window * 0.99:
            return True

    return False


def get_overflow_patterns() -> list[re.Pattern[str]]:
    return list(_OVERFLOW_PATTERNS)


__all__ = ["get_overflow_patterns", "is_context_overflow"]
