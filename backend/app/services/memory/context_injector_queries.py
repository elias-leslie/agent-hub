"""Episode retrieval queries for context injection."""

import logging
import re
from typing import Any

from .episode_validation import EpisodeValidator
from .memory_utils import build_group_id
from .repository import MemoryRepository, get_memory_repository
from .service import MemoryScope

logger = logging.getLogger(__name__)
_REFERENCE_MIN_SCORE = 0.2
_REFERENCE_SEARCH_LIMIT = 8
_REFERENCE_TOP_K = 3
_TOKEN_PATTERN = re.compile(r"[a-z0-9_./-]{3,}")


def _memory_to_dict(mem: Any) -> dict[str, Any]:
    """Convert a Memory ORM object to a dict using MemoryRepository._to_dict."""
    return MemoryRepository._to_dict(mem)


def _is_reference_candidate(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("is_session_summary"):
        return False

    content = str(candidate.get("content") or "")
    source_description = str(candidate.get("source_description") or "")
    if EpisodeValidator.validate_reusability_simple(content):
        return False
    return "session_summary" not in source_description


async def get_episodes_by_tier(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get episodes by injection_tier field.

    This is the tier-first query method that replaces keyword matching.

    Args:
        tier: The injection tier (mandate/guardrail/reference)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of episode dicts with uuid, content, created_at, etc.
    """
    repo = get_memory_repository()
    group_id = build_group_id(scope, scope_id)

    try:
        memories = await repo.list_by_scope_and_tier(
            tier=tier,
            group_id=group_id,
            status="active",
        )
        return [_memory_to_dict(m) for m in memories]
    except Exception as e:
        logger.warning("Failed to get episodes by tier %s: %s", tier, e)
        return []


async def get_auto_inject_references(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference-tier episodes with auto_inject=true.

    These are references that should be injected like mandates/guardrails,
    but are categorized separately for organizational purposes.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of auto-inject reference episode dicts
    """
    repo = get_memory_repository()
    group_id = build_group_id(scope, scope_id)

    try:
        memories = await repo.list_by_scope_and_tier(
            tier="reference",
            auto_inject=True,
            group_id=group_id,
            status="active",
        )
        return [_memory_to_dict(m) for m in memories]
    except Exception as e:
        logger.warning("Failed to get auto-inject references: %s", e)
        return []


async def build_reference_toon_index(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[tuple[str, str | None, str, bool]]:
    """
    Get all reference-tier episodes for TOON index generation.

    Returns list of (uuid, summary, content, pinned) tuples for TOON formatting.
    Summary is used for display; content is fallback only.
    Pinned items are expanded to full content in format_context_with_reference_index.
    """
    episodes = await get_episodes_by_tier("reference", scope, scope_id)
    return [
        (ep.get("uuid", ""), ep.get("summary"), ep.get("content", ""), ep.get("pinned", False))
        for ep in episodes
    ]
