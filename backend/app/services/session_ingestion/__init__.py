"""Canonical session ingestion surface."""

from .models import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    NormalizedEvent,
    SessionUpsertRequest,
    SessionUpsertResult,
)
from .service import append_normalized_events, finalize_session, upsert_session

__all__ = [
    "AppendNormalizedEventsRequest",
    "AppendNormalizedEventsResult",
    "FinalizeSessionRequest",
    "FinalizeSessionResult",
    "NormalizedEvent",
    "SessionUpsertRequest",
    "SessionUpsertResult",
    "append_normalized_events",
    "finalize_session",
    "upsert_session",
]
