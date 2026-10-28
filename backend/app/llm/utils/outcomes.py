"""Typed provider outcomes carried on ``AssistantMessage.diagnostics``.

``StopReason`` stays the locked pi-mono set, so a refusal, a turn answered by a
different model, or a subscription usage limit travels as one
``provider_outcome`` diagnostic. Workflow policy reads it back with
``outcome_of`` instead of matching error text.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

from .diagnostics import AssistantMessageDiagnostic, append_assistant_message_diagnostic

OUTCOME_DIAGNOSTIC = "provider_outcome"

# "interrupted": the stream died (transport error, progress timeout, runaway tool call); the turn can be re-sent.
OutcomeKind = Literal["refused", "substituted", "usage_limit", "interrupted"]


@dataclass(slots=True, frozen=True)
class ProviderOutcome:
    kind: OutcomeKind
    requested_model: str
    # The model that actually answered, when the provider reported one.
    served_model: str | None = None
    # Provider safety category for refusals and refusal-driven substitutions (cyber, bio, ...).
    category: str | None = None
    explanation: str | None = None
    # Usage-limit window (five_hour, seven_day, ...) and its reset as unix seconds.
    window: str | None = None
    resets_at: int | None = None
    request_id: str | None = None


_SNAPSHOT_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


def is_model_switch(requested: str | None, served: str | None) -> bool:
    """True when ``served`` is a different model than ``requested``.

    Provider prefixes, case and dated snapshot suffixes (``-2026-04-23``) are the
    same model, so they never count as a switch.
    """

    if not requested or not served:
        return False

    def bare(value: str) -> str:
        return _SNAPSHOT_SUFFIX.sub("", value.strip().lower().rsplit("/", 1)[-1])

    return bare(requested) != bare(served)


def outcome_details(outcome: ProviderOutcome) -> dict[str, Any]:
    """The populated fields of ``outcome``, as stored in diagnostics and session events."""

    return {key: value for key, value in asdict(outcome).items() if value is not None}


def record_outcome(message: Any, outcome: ProviderOutcome) -> None:
    """Attach ``outcome`` to ``message`` as a ``provider_outcome`` diagnostic."""

    details = outcome_details(outcome)
    append_assistant_message_diagnostic(
        message,
        AssistantMessageDiagnostic(type=OUTCOME_DIAGNOSTIC, timestamp=int(time.time() * 1000), details=details),
    )


def outcome_of(message: Any) -> ProviderOutcome | None:
    """Return the last ``provider_outcome`` recorded on ``message``, if any."""

    names = {field.name for field in fields(ProviderOutcome)}
    for diagnostic in reversed(getattr(message, "diagnostics", None) or []):
        if diagnostic.type == OUTCOME_DIAGNOSTIC and diagnostic.details:
            return ProviderOutcome(**{key: value for key, value in diagnostic.details.items() if key in names})
    return None


__all__ = [
    "OUTCOME_DIAGNOSTIC",
    "OutcomeKind",
    "ProviderOutcome",
    "is_model_switch",
    "outcome_details",
    "outcome_of",
    "record_outcome",
]
