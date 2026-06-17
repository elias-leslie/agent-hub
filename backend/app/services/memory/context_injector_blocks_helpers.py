"""Helper utilities for context_injector_blocks.py.

Shared episode-to-result conversion logic and mandate filtering.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from .applicability import normalize_applicability, normalize_context_kind
from .service import MemoryCategory, MemoryScope, MemorySearchResult, MemorySource

logger = logging.getLogger(__name__)


def _safe_created_at(raw: Any) -> datetime:
    """Safely extract a datetime from a dict value, falling back to now(UTC)."""
    if isinstance(raw, datetime):
        return raw
    return datetime.now(UTC)


def _safe_tags(raw: Any) -> list[str]:
    """Normalize nullable or malformed tags into a list of strings."""
    if isinstance(raw, list):
        return [str(tag) for tag in raw if tag is not None]
    return []


def _safe_int(raw: Any) -> int:
    """Normalize nullable numeric values to ints."""
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _safe_confidence(raw: Any) -> float | None:
    """Normalize nullable confidence values to floats."""
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _safe_scope(raw: Any) -> MemoryScope | None:
    if isinstance(raw, MemoryScope):
        return raw
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value.startswith("project"):
        return MemoryScope.PROJECT
    if value == MemoryScope.GLOBAL.value:
        return MemoryScope.GLOBAL
    return None


def _safe_category(ep: dict[str, Any]) -> MemoryCategory | None:
    raw = (
        ep.get("injection_tier")
        or ep.get("category")
        or ep.get("memory_type")
        or ep.get("tier")
    )
    if isinstance(raw, int):
        raw = {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}.get(raw)
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value.isdigit():
        value = {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}.get(
            int(value),
            value,
        )
    try:
        return MemoryCategory(value)
    except ValueError:
        return None


def _safe_optional_datetime(raw: Any) -> datetime | None:
    """Normalize optional datetimes without inventing fallback timestamps."""
    if isinstance(raw, datetime):
        return raw
    return None


def _compact_content(ep: dict[str, Any]) -> str | None:
    """Return reviewed compact prompt text from top-level or metadata."""
    compact = ep.get("compact_content")
    if isinstance(compact, str) and compact.strip():
        return compact.strip()
    metadata = ep.get("metadata")
    if isinstance(metadata, dict):
        compact = metadata.get("compact_content")
        if isinstance(compact, str) and compact.strip():
            return compact.strip()
    return None


def episode_to_result(ep: dict[str, Any], source: MemorySource = MemorySource.SYSTEM) -> MemorySearchResult | None:
    """Convert a raw episode dict to a MemorySearchResult, or None if content is missing."""
    content = ep.get("content") or ""
    uuid = ep.get("uuid", "")
    if not content:
        return None

    created_at = _safe_created_at(ep.get("created_at"))

    return MemorySearchResult(
        uuid=uuid,
        content=content,
        compact_content=_compact_content(ep),
        summary=ep.get("summary"),
        source=source,
        relevance_score=float(ep.get("relevance_score") or 1.0),
        created_at=created_at,
        facts=[content],
        scope=_safe_scope(ep.get("scope")),
        scope_id=ep.get("scope_id"),
        category=_safe_category(ep),
        review_status=str(ep.get("review_status") or "pending"),
        sensitivity_tier=str(ep.get("sensitivity_tier") or "normal"),
        last_reviewed_at=_safe_optional_datetime(ep.get("last_reviewed_at")),
        pinned=ep.get("pinned", False),
        tags=_safe_tags(ep.get("tags")),
        loaded_count=_safe_int(ep.get("loaded_count")),
        referenced_count=_safe_int(ep.get("referenced_count")),
        token_count=_safe_int(ep.get("token_count")),
        confidence=_safe_confidence(ep.get("confidence")),
        last_accessed_at=_safe_optional_datetime(ep.get("last_accessed_at")),
        source_description=ep.get("source_description"),
        auto_inject=bool(ep.get("auto_inject", False)),
        display_order=_safe_int(ep.get("display_order")) or 50,
        context_kind=normalize_context_kind(
            ep.get("context_kind"),
            memory_type=ep.get("memory_type"),
            tier=ep.get("tier"),
        ),
        applicability=normalize_applicability(ep.get("applicability")),
        render_mode=ep.get("render_mode"),
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

    if uuid in demoted_uuids and not ep.get("pinned", False):
        logger.debug("Excluding demoted mandate: uuid=%s", uuid[:8])
        return None

    created_at = _safe_created_at(ep.get("created_at"))

    try:
        return MemorySearchResult(
            uuid=uuid,
            content=content,
            compact_content=_compact_content(ep),
            summary=ep.get("summary"),
            source=MemorySource.SYSTEM,
            relevance_score=1.0,
            created_at=created_at,
            facts=[content],
            scope=_safe_scope(ep.get("scope")),
            scope_id=ep.get("scope_id"),
            category=_safe_category(ep),
            review_status=str(ep.get("review_status") or "pending"),
            sensitivity_tier=str(ep.get("sensitivity_tier") or "normal"),
            last_reviewed_at=_safe_optional_datetime(ep.get("last_reviewed_at")),
            pinned=ep.get("pinned", False),
            tags=_safe_tags(ep.get("tags")),
            loaded_count=_safe_int(ep.get("loaded_count")),
            referenced_count=_safe_int(ep.get("referenced_count")),
            token_count=_safe_int(ep.get("token_count")),
            confidence=_safe_confidence(ep.get("confidence")),
            last_accessed_at=_safe_optional_datetime(ep.get("last_accessed_at")),
            source_description=ep.get("source_description"),
            auto_inject=bool(ep.get("auto_inject", False)),
            display_order=_safe_int(ep.get("display_order")) or 50,
            context_kind=normalize_context_kind(
                ep.get("context_kind"),
                memory_type=ep.get("memory_type"),
                tier=ep.get("tier"),
            ),
            applicability=normalize_applicability(ep.get("applicability")),
            render_mode=ep.get("render_mode"),
        )
    except Exception as e:
        logger.warning("Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50])
        return None


def guardrail_episode_to_result(ep: dict[str, Any]) -> MemorySearchResult | None:
    """Convert a guardrail episode dict to a MemorySearchResult.

    Returns None if content is missing.
    """
    content = ep.get("content") or ""
    uuid = ep.get("uuid", "")
    if not content:
        return None

    created_at = _safe_created_at(ep.get("created_at"))

    return MemorySearchResult(
        uuid=uuid,
        content=content,
        compact_content=_compact_content(ep),
        summary=ep.get("summary"),
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=created_at,
        facts=[content],
        scope=_safe_scope(ep.get("scope")),
        scope_id=ep.get("scope_id"),
        category=_safe_category(ep),
        review_status=str(ep.get("review_status") or "pending"),
        sensitivity_tier=str(ep.get("sensitivity_tier") or "normal"),
        last_reviewed_at=_safe_optional_datetime(ep.get("last_reviewed_at")),
        pinned=ep.get("pinned", False),
        tags=_safe_tags(ep.get("tags")),
        loaded_count=_safe_int(ep.get("loaded_count")),
        referenced_count=_safe_int(ep.get("referenced_count")),
        token_count=_safe_int(ep.get("token_count")),
        confidence=_safe_confidence(ep.get("confidence")),
        last_accessed_at=_safe_optional_datetime(ep.get("last_accessed_at")),
        source_description=ep.get("source_description"),
        auto_inject=bool(ep.get("auto_inject", False)),
        display_order=_safe_int(ep.get("display_order")) or 50,
        context_kind=normalize_context_kind(
            ep.get("context_kind"),
            memory_type=ep.get("memory_type"),
            tier=ep.get("tier"),
        ),
        applicability=normalize_applicability(ep.get("applicability")),
        render_mode=ep.get("render_mode"),
    )
