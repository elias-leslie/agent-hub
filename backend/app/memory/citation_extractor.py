"""Out-of-band citation extraction (per convergence-map.md D9).

The new pipeline never embeds citation logic inside an adapter or inside the
``AssistantMessage`` content shape. Instead, the orchestrator hands the
assembled final assistant text to :func:`extract_cited_uuids`, which scans
for UUID-prefix references and resolves them via the memory store. The
returned list of UUIDs becomes the ``cited_uuids`` HTTP response field
(see ``downstream-consumers.md`` Section 6).

Persisting cite events / metrics is a separate concern handled by the
legacy ``citation_tracker.py`` until Phase 4 retires it; this module is
intentionally only the extraction primitive.
"""

from __future__ import annotations

import logging

from app.services.memory import (
    extract_uuid_prefixes,
    parse_memory_group_id,
    resolve_full_uuids,
)

logger = logging.getLogger(__name__)


def _build_group_id(memory_group_id: str | None) -> str:
    """Derive the group_id string from memory_group_id."""
    scope, scope_id = parse_memory_group_id(memory_group_id)
    if scope.value == "global":
        return "global"
    return f"{scope.value}-{scope_id}"


async def extract_cited_uuids(content: str, memory_group_id: str | None) -> list[str]:
    """Scan ``content`` for memory UUID prefixes and resolve to full UUIDs.

    Returns ``[]`` when no prefixes appear. This is the out-of-band step the
    orchestrator runs after the adapter produces its final ``AssistantMessage``
    text — the adapter itself remains memory-agnostic.
    """
    cited_prefixes = extract_uuid_prefixes(content)
    if not cited_prefixes:
        return []
    group_id = _build_group_id(memory_group_id)
    return list((await resolve_full_uuids(cited_prefixes, group_id)).values())


__all__ = ["extract_cited_uuids"]
