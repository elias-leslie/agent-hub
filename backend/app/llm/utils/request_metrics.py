"""One compact record per model request, carried on ``AssistantMessage.diagnostics``.

Providers attach what only they can see (SSE keepalives, longest tool-argument stream, gaps between frames);
``tool_loop.run_turn`` adds the retries the turn needed. Session persistence reads it back with
``request_metrics_of`` and stores it as a ``model_request`` audit event, so a slow run can be told from a dead
one after the fact instead of only in a DEBUG log line.
"""

from __future__ import annotations

import time
from typing import Any

from .diagnostics import AssistantMessageDiagnostic, append_assistant_message_diagnostic

REQUEST_METRICS_DIAGNOSTIC = "request_metrics"


def request_metrics_of(message: Any) -> dict[str, Any] | None:
    """The last ``request_metrics`` details recorded on ``message``, if any."""

    for diagnostic in reversed(getattr(message, "diagnostics", None) or []):
        if diagnostic.type == REQUEST_METRICS_DIAGNOSTIC and diagnostic.details is not None:
            return diagnostic.details
    return None


def record_request_metrics(message: Any, **details: Any) -> None:
    """Attach ``details`` to ``message``; fields already recorded are updated, others kept."""

    existing = request_metrics_of(message)
    if existing is not None:
        existing.update(details)
        return
    append_assistant_message_diagnostic(
        message,
        AssistantMessageDiagnostic(type=REQUEST_METRICS_DIAGNOSTIC, timestamp=int(time.time() * 1000), details=dict(details)),
    )


__all__ = ["REQUEST_METRICS_DIAGNOSTIC", "record_request_metrics", "request_metrics_of"]
