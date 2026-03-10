"""Canonical session ingestion surface."""

from .models import (
    AppendNormalizedEventsRequest,
    AppendNormalizedEventsResult,
    FinalizeSessionRequest,
    FinalizeSessionResult,
    NormalizedEvent,
    SessionHeartbeatRequest,
    SessionHeartbeatResult,
    SessionUpsertRequest,
    SessionUpsertResult,
    TranscriptIngestRequest,
    TranscriptIngestResult,
)
from .service import (
    append_normalized_events,
    finalize_session,
    heartbeat_session,
    ingest_transcript_events,
    upsert_session,
)

__all__ = [
    "AppendNormalizedEventsRequest",
    "AppendNormalizedEventsResult",
    "FinalizeSessionRequest",
    "FinalizeSessionResult",
    "NormalizedEvent",
    "SessionHeartbeatRequest",
    "SessionHeartbeatResult",
    "SessionUpsertRequest",
    "SessionUpsertResult",
    "TranscriptIngestRequest",
    "TranscriptIngestResult",
    "append_normalized_events",
    "finalize_session",
    "heartbeat_session",
    "ingest_transcript_events",
    "upsert_session",
]
