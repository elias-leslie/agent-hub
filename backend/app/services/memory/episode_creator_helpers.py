"""Private helper functions for episode_creator.

Extracted to keep episode_creator.py focused on orchestration.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from app.llm.api_key_pool import is_billing_failure

from .applicability import normalize_applicability, normalize_context_kind
from .embedder import EMBEDDING_MODEL
from .episode_creator_models import CreateResult
from .episode_validation import EpisodeValidationError, EpisodeValidator
from .ingestion_config import LEARNING, IngestionConfig
from .repository import MemoryRepository

logger = logging.getLogger(__name__)

MAX_SOURCE_COMPACT_CONTENT_CHARS = 420


def validate_content(
    content: str,
    config: IngestionConfig,
    *,
    bypass_compactness: bool = False,
) -> CreateResult | None:
    """Return a failure CreateResult if validation fails, else None."""
    if not config.validate:
        return None
    validation_error = EpisodeValidator.validate_content_simple(
        content, bypass_compactness=bypass_compactness
    )
    if validation_error:
        return CreateResult(success=False, validation_error=validation_error)
    if config == LEARNING:
        reusability_error = EpisodeValidator.validate_reusability_simple(content)
        if reusability_error:
            return CreateResult(success=False, validation_error=reusability_error)
    return None


def _collapse_whitespace(content: str) -> str:
    return " ".join(content.split())


def build_source_quality_metadata(
    content: str,
    metadata: dict[str, object] | None,
    *,
    checked_at: datetime,
    tier_name: str,
    replace_existing: bool = False,
) -> dict[str, object] | None:
    """Mark source-authored memories that are already prompt-ready compact."""
    enriched = dict(metadata or {})
    compact_content = _collapse_whitespace(content)
    if len(compact_content) > MAX_SOURCE_COMPACT_CONTENT_CHARS:
        if replace_existing:
            for key in (
                "compact_content",
                "compact_status",
                "source_compact_validated_at",
                "source_quality_checked_at",
                "source_quality_method",
            ):
                enriched.pop(key, None)
            return enriched
        return metadata
    try:
        EpisodeValidator.validate_content(compact_content, tier=tier_name)
    except EpisodeValidationError:
        if replace_existing:
            for key in (
                "compact_content",
                "compact_status",
                "source_compact_validated_at",
                "source_quality_checked_at",
                "source_quality_method",
            ):
                enriched.pop(key, None)
            return enriched
        return metadata

    checked_at_iso = checked_at.isoformat()
    if replace_existing:
        enriched["compact_content"] = compact_content
        enriched["compact_status"] = "source_ready"
        enriched["source_compact_validated_at"] = checked_at_iso
        enriched["source_quality_checked_at"] = checked_at_iso
        enriched["source_quality_method"] = "format_standard"
    else:
        enriched.setdefault("compact_content", compact_content)
        enriched.setdefault("compact_status", "source_ready")
        enriched.setdefault("source_compact_validated_at", checked_at_iso)
        enriched.setdefault("source_quality_checked_at", checked_at_iso)
        enriched.setdefault("source_quality_method", "format_standard")
    return enriched


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
    """Build a CreateResult for Gemini rate-limit and billing exceptions.

    Gemini reports a depleted prepay balance as 429 RESOURCE_EXHAUSTED, the same
    status as a quota bounce, so the two have to be told apart here. Telling the
    operator to wait out a billing stop would be wrong: the balance does not
    refill on its own, and every retry fails identically until someone tops the
    account up.
    """
    quota = extract_gemini_quota_details(e)
    quota_summary = ""
    if quota.get("quota_metric"):
        quota_summary = (
            f" [metric={quota.get('quota_metric')}"
            f" limit={quota.get('quota_limit', '?')}"
            f" consumer={quota.get('consumer', '?')}]"
        )
    if is_billing_failure(e):
        detail = (
            "Every Gemini account in the key pool is out of credit, so embedding "
            f"failed (model: {EMBEDDING_MODEL}).{quota_summary} Top up billing at "
            "https://ai.studio/projects or add a funded key; retrying will not clear this."
        )
        logger.error("Gemini billing stop during embed%s: %s", quota_summary, e)
        return CreateResult(success=False, validation_error=detail)
    detail = (
        "Gemini API rate limit hit during embedding "
        f"(model: {EMBEDDING_MODEL}).{quota_summary} Wait a few minutes and retry."
    )
    logger.warning("Gemini rate limit during embed%s: %s", quota_summary, e)
    return CreateResult(success=False, validation_error=detail)


def extract_gemini_quota_details(e: Exception) -> dict[str, str]:
    """Extract quota metadata from a Gemini API error."""
    info: dict[str, str] = {}
    details_obj = getattr(e, "details", None)
    if details_obj and isinstance(details_obj, dict):
        error_block = details_obj.get("error", details_obj)
        info["status"] = str(error_block.get("status", ""))
        info["message"] = str(error_block.get("message", ""))[:200]
        for detail in error_block.get("details", []):
            metadata = detail.get("metadata", {})
            if "quota_metric" in metadata:
                info["quota_metric"] = metadata["quota_metric"]
            if "quota_limit_value" in metadata:
                info["quota_limit"] = metadata["quota_limit_value"]
            if "consumer" in metadata:
                info["consumer"] = metadata["consumer"]
            if detail.get("retryDelay"):
                info["retry_delay"] = detail["retryDelay"]

    response = getattr(e, "response", None)
    if response and not info.get("quota_metric"):
        body = getattr(response, "text", None)
        if body and isinstance(body, str):
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {}
            error_block = data.get("error", data) if isinstance(data, dict) else {}
            if isinstance(error_block, dict):
                if not info.get("status"):
                    info["status"] = str(error_block.get("status", ""))
                if not info.get("message"):
                    info["message"] = str(error_block.get("message", ""))[:200]
                for detail in error_block.get("details", []):
                    if not isinstance(detail, dict):
                        continue
                    metadata = detail.get("metadata", {})
                    if isinstance(metadata, dict):
                        if "quota_metric" in metadata:
                            info["quota_metric"] = metadata["quota_metric"]
                        if "quota_limit_value" in metadata:
                            info["quota_limit"] = metadata["quota_limit_value"]
                        if "consumer" in metadata:
                            info["consumer"] = metadata["consumer"]
                    if detail.get("retryDelay"):
                        info["retry_delay"] = detail["retryDelay"]
    return {k: v for k, v in info.items() if v}
