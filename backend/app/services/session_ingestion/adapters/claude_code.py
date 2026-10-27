"""Claude Code transcript adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

from app.services.session_ingestion.models import NormalizedEvent, SessionUpsertRequest

from .base import ProviderBoundary, ProviderSessionRef
from .transcript_parsers import contained_transcript_path, read_incremental_transcript_events

_SYNTHETIC_MODEL = "<synthetic>"
_MODEL_SCAN_LINES = 2000


def first_transcript_model(transcript_path: str | None) -> str | None:
    """Model of the first real assistant message in a Claude Code transcript.

    Claude Code's ``<synthetic>`` placeholder turns (refusals, API errors) are not a model.
    """
    path = contained_transcript_path(transcript_path) if transcript_path else None
    if path is None or path.suffix != ".jsonl":
        return None
    try:
        with path.open(encoding="utf-8", errors="replace") as transcript:
            for index, line in enumerate(transcript):
                if index >= _MODEL_SCAN_LINES:
                    break
                if '"assistant"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = record.get("message") if isinstance(record, dict) and record.get("type") == "assistant" else None
                model = message.get("model") if isinstance(message, dict) else None
                if isinstance(model, str) and model.strip() and model != _SYNTHETIC_MODEL:
                    return model.strip()
    except OSError:
        return None
    return None


class ClaudeCodeTranscriptAdapter:
    """Translate Claude Code JSONL transcripts into normalized events."""

    provider_name = "claude"

    async def discover_sessions(self) -> Sequence[ProviderSessionRef]:
        return []

    async def build_session_metadata(self, session_ref: ProviderSessionRef) -> SessionUpsertRequest:
        model = await asyncio.to_thread(first_transcript_model, session_ref.source_id)
        return SessionUpsertRequest(
            session_id=session_ref.provider_session_id,
            project_id="unknown",
            provider=self.provider_name,
            model=model or "unknown",
            session_type="claude_code",
            provider_metadata={"transcript_path": session_ref.source_id} if session_ref.source_id else {},
        )

    async def read_new_events(
        self,
        session_ref: ProviderSessionRef,
        checkpoint: str | None = None,
    ) -> tuple[list[NormalizedEvent], str | None]:
        if not session_ref.source_id:
            return [], checkpoint
        return await asyncio.to_thread(read_incremental_transcript_events, session_ref.source_id, checkpoint)

    async def detect_boundaries(
        self,
        session_ref: ProviderSessionRef,
        checkpoint: str | None = None,
    ) -> list[ProviderBoundary]:
        if checkpoint is None:
            return [ProviderBoundary(boundary_type="opened")]
        return []
