"""Typed provider outcomes carried on ``AssistantMessage.diagnostics``.

``StopReason`` stays the locked pi-mono set, so a refusal, a turn answered by a
different model, or a subscription usage limit travels as one
``provider_outcome`` diagnostic. Workflow policy reads it back with
``outcome_of`` instead of matching error text.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

from .diagnostics import AssistantMessageDiagnostic, append_assistant_message_diagnostic

OUTCOME_DIAGNOSTIC = "provider_outcome"

OutcomeKind = Literal["refused", "substituted", "usage_limit"]


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


def record_outcome(message: Any, outcome: ProviderOutcome) -> None:
    """Attach ``outcome`` to ``message`` as a ``provider_outcome`` diagnostic."""

    details = {key: value for key, value in asdict(outcome).items() if value is not None}
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


__all__ = ["OUTCOME_DIAGNOSTIC", "OutcomeKind", "ProviderOutcome", "outcome_of", "record_outcome"]
