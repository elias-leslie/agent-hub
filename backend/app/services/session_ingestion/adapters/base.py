"""Provider adapter interface for normalized session ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, Field

from app.services.session_ingestion.models import NormalizedEvent, SessionUpsertRequest


class ProviderSessionRef(BaseModel):
    """Provider-owned session descriptor used during discovery."""

    provider_session_id: str
    source_id: str | None = Field(default=None, description="Transcript path, stream id, or log source")


class ProviderBoundary(BaseModel):
    """Detected lifecycle boundary for a provider session."""

    boundary_type: str = Field(
        ...,
        description="opened, resumed, compacted, finalized, or provider-specific lifecycle marker",
    )
    checkpoint: str | None = Field(
        default=None,
        description="Opaque checkpoint associated with the detected boundary",
    )


class SessionIngestionAdapter(Protocol):
    """Translation-only contract for external session providers."""

    provider_name: str

    async def discover_sessions(self) -> Sequence[ProviderSessionRef]:
        """Discover provider sessions available for ingestion."""

    async def build_session_metadata(self, session_ref: ProviderSessionRef) -> SessionUpsertRequest:
        """Build canonical session metadata for a provider session."""

    async def read_new_events(
        self,
        session_ref: ProviderSessionRef,
        checkpoint: str | None = None,
    ) -> tuple[list[NormalizedEvent], str | None]:
        """Translate raw provider data into normalized events and return the next checkpoint."""

    async def detect_boundaries(
        self,
        session_ref: ProviderSessionRef,
        checkpoint: str | None = None,
    ) -> list[ProviderBoundary]:
        """Detect lifecycle boundaries for an ingested provider session."""
