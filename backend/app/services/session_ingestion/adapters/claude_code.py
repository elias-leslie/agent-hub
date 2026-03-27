"""Claude Code transcript adapter."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.session_ingestion.models import NormalizedEvent, SessionUpsertRequest

from .base import ProviderBoundary, ProviderSessionRef
from .transcript_parsers import read_incremental_transcript_events


class ClaudeCodeTranscriptAdapter:
    """Translate Claude Code JSONL transcripts into normalized events."""

    provider_name = "claude"

    async def discover_sessions(self) -> Sequence[ProviderSessionRef]:
        return []

    async def build_session_metadata(self, session_ref: ProviderSessionRef) -> SessionUpsertRequest:
        return SessionUpsertRequest(
            session_id=session_ref.provider_session_id,
            project_id="unknown",
            provider=self.provider_name,
            model="unknown",
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
        return read_incremental_transcript_events(session_ref.source_id, checkpoint)

    async def detect_boundaries(
        self,
        session_ref: ProviderSessionRef,
        checkpoint: str | None = None,
    ) -> list[ProviderBoundary]:
        if checkpoint is None:
            return [ProviderBoundary(boundary_type="opened")]
        return []
