"""Private helper functions for episode_creator_core.

Extracted to keep episode_creator_core.py focused on orchestration.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .applicability import normalize_applicability, normalize_context_kind
from .embedder import EMBEDDING_MODEL
from .episode_creator_models import CreateResult
from .episode_validation import EpisodeValidator
from .ingestion_config import LEARNING, IngestionConfig
from .repository import MemoryRepository

logger = logging.getLogger(__name__)


def validate_content(content: str, config: IngestionConfig) -> CreateResult | None:
    """Return a failure CreateResult if validation fails, else None."""
    if not config.validate:
        return None
    validation_error = EpisodeValidator.validate_content_simple(content)
    if validation_error:
        return CreateResult(success=False, validation_error=validation_error)
    if config == LEARNING:
        reusability_error = EpisodeValidator.validate_reusability_simple(content)
        if reusability_error:
            return CreateResult(success=False, validation_error=reusability_error)
    return None


async def insert_memory(
    repo: MemoryRepository,
    *,
    content: str,
    name: str,
    group_id: str,
    source_description: str,
    reference_time: datetime,
    embedding: list[float],
    context_kind: str | None,
    applicability: dict[str, object] | None,
    tags: list[str] | None,
    tier: int,
    summary: str | None,
    metadata: dict[str, object] | None,
    sensitivity_tier: str = "normal",
    token_count: int,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> str:
    """Insert a memory row via MemoryRepository.create() and return its UUID."""
    normalized_context_kind = normalize_context_kind(
        context_kind,
        memory_type="episode",
        tier=tier,
    ).value
    normalized_applicability = normalize_applicability(applicability).model_dump()
    memory = await repo.create(
        content=content,
        name=name,
        memory_type="episode",
        group_id=group_id,
        source_description=source_description,
        embedding=embedding,
        context_kind=normalized_context_kind,
        applicability=normalized_applicability,
        tags=tags,
        tier=tier,
        summary=summary,
        metadata=metadata,
        sensitivity_tier=sensitivity_tier,
        token_count=token_count,
        valid_at=reference_time,
        changed_by=changed_by,
        change_reason=change_reason,
    )
    return str(memory.id)


def is_rate_limit_error(e: Exception) -> bool:
    """Return True if the exception represents a Gemini rate-limit error."""
    msg = str(e).lower()
    return "rate limit" in msg or "429" in msg or "resource exhausted" in msg


def handle_rate_limit_error(e: Exception) -> CreateResult:
    """Build a CreateResult for Gemini rate-limit exceptions."""
    from app.adapters.gemini_errors import extract_gemini_quota_details

    quota = extract_gemini_quota_details(e)
    quota_summary = ""
    if quota.get("quota_metric"):
        quota_summary = (
            f" [metric={quota.get('quota_metric')}"
            f" limit={quota.get('quota_limit', '?')}"
            f" consumer={quota.get('consumer', '?')}]"
        )
    detail = (
        "Gemini API rate limit hit during embedding "
        f"(model: {EMBEDDING_MODEL}).{quota_summary} Wait a few minutes and retry."
    )
    logger.warning("Gemini rate limit during embed%s: %s", quota_summary, e)
    return CreateResult(success=False, validation_error=detail)
