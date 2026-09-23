"""Unavailable legacy agent-output memory extraction entry points."""

from __future__ import annotations

from typing import Any

from app.services.curator_retirement import curator_unavailable

from .memory_models import MemoryScope

DEFAULT_EXTRACTOR_AGENT = "memory-curator"


async def extract_agent_output_candidates(
    output: str,
    *,
    extractor_agent_slug: str = DEFAULT_EXTRACTOR_AGENT,
) -> list[Any]:
    """Reject the retired model extraction path before provider access."""
    curator_unavailable()


async def ingest_agent_output_candidates(
    output: str,
    *,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    source_agent_slug: str | None = None,
    session_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Reject the retired automatic ingestion path before storage access."""
    curator_unavailable()
