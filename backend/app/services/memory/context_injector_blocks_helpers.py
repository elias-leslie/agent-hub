"""Helper utilities for context_injector_blocks.py.

Shared episode-to-result conversion logic and mandate filtering.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from .query_builders import convert_neo4j_datetime
from .service import MemorySearchResult, MemorySource

logger = logging.getLogger(__name__)


def episode_to_result(ep: dict[str, Any], source: MemorySource = MemorySource.SYSTEM) -> MemorySearchResult | None:
    """Convert a raw episode dict to a MemorySearchResult, or None if content is missing."""
    content = ep.get("content") or ""
    uuid = ep.get("uuid", "")
    if not content:
        return None

    created_at = ep.get("created_at")
    if created_at is not None and hasattr(created_at, "to_native"):
        created_at = created_at.to_native()
    if not isinstance(created_at, datetime):
        created_at = datetime.now(UTC)

    return MemorySearchResult(
        uuid=uuid,
        content=content,
        source=source,
        relevance_score=1.0,
        created_at=created_at,
        facts=[content],
        tags=ep.get("tags", []),
    )


def mandate_episode_to_result(ep: dict[str, Any], demoted_uuids: set[str]) -> MemorySearchResult | None:
    """Convert a mandate episode dict to MemorySearchResult with demotion check.

    Returns None if content is missing or the episode is demoted.
    Also supports the 'pinned' field.
    """
    content = ep.get("content") or ""
    uuid = ep.get("uuid", "")

    if not content:
        logger.debug("Skipping mandate without content: %s", uuid[:8] if uuid else "?")
        return None

    if uuid in demoted_uuids:
        logger.debug("Excluding demoted mandate: uuid=%s", uuid[:8])
        return None

    created_at = convert_neo4j_datetime(ep.get("created_at"))
    if not isinstance(created_at, datetime):
        created_at = datetime.now(UTC)

    try:
        return MemorySearchResult(
            uuid=uuid,
            content=content,
            source=MemorySource.SYSTEM,
            relevance_score=1.0,
            created_at=created_at,
            facts=[content],
            pinned=ep.get("pinned", False),
            tags=ep.get("tags", []),
        )
    except Exception as e:
        logger.warning("Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50])
        return None


def guardrail_episode_to_result(ep: dict[str, Any]) -> MemorySearchResult | None:
    """Convert a guardrail episode dict to a MemorySearchResult.

    Returns None if content is missing.
    Uses convert_neo4j_datetime for created_at (matches original guardrail logic).
    """
    content = ep.get("content") or ""
    uuid = ep.get("uuid", "")
    if not content:
        return None

    created_at = convert_neo4j_datetime(ep.get("created_at"))
    if not isinstance(created_at, datetime):
        created_at = datetime.now(UTC)

    return MemorySearchResult(
        uuid=uuid,
        content=content,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=created_at,
        facts=[content],
        tags=ep.get("tags", []),
    )
