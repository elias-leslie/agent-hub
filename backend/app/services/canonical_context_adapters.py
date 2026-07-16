"""Lossless adapters from the canonical context contract to legacy surfaces.

Selection and ordering live exclusively in ``runtime_context``.  This module
only projects an already-built delivery into compatibility shapes used by the
progressive-context API, injection metrics, and prompt previews.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.memory_models import (
    MemoryCategory,
    MemoryContextKind,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.runtime_context import (
    CanonicalContextBlock,
    CanonicalContextDeliveryResponse,
)


class CanonicalContextUnavailable(RuntimeError):
    """Raised so the existing resilience layer can retry a failed delivery."""


def require_canonical_context(
    delivery: CanonicalContextDeliveryResponse,
) -> CanonicalContextDeliveryResponse:
    """Return a successful delivery or raise with its authoritative failure."""
    if delivery.status == "ok":
        return delivery
    failure = delivery.failure
    detail = (
        f"{failure.error_type}: {failure.error_message}"
        if failure is not None
        else "canonical context delivery failed"
    )
    raise CanonicalContextUnavailable(detail)


def memory_blocks(
    delivery: CanonicalContextDeliveryResponse,
) -> list[CanonicalContextBlock]:
    """Return ordered memory-origin blocks from a delivery."""
    return [
        block
        for block in delivery.blocks
        if block.provenance.source_type == "memory"
    ]


def _memory_category(kind: str) -> MemoryCategory:
    return {
        "mandate": MemoryCategory.MANDATE,
        "guardrail": MemoryCategory.GUARDRAIL,
        "archive": MemoryCategory.ARCHIVE,
    }.get(kind, MemoryCategory.REFERENCE)


def _context_kind(kind: str) -> MemoryContextKind:
    if kind in {"mandate", "guardrail"}:
        return MemoryContextKind.POLICY
    if kind == "capability":
        return MemoryContextKind.CAPABILITY
    return MemoryContextKind.REFERENCE


def _scope(block: CanonicalContextBlock) -> MemoryScope | None:
    raw_scope = block.provenance.scope
    if raw_scope == MemoryScope.GLOBAL.value:
        return MemoryScope.GLOBAL
    if raw_scope == MemoryScope.PROJECT.value or block.provenance.scope_id:
        return MemoryScope.PROJECT
    return None


def _memory_result(block: CanonicalContextBlock) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=block.provenance.source_id,
        content=block.content,
        rendered_content=block.content,
        summary=block.title,
        review_status=block.provenance.review_status or "pending",
        sensitivity_tier=block.provenance.sensitivity_tier or "normal",
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        facts=[],
        scope=_scope(block),
        scope_id=block.provenance.scope_id,
        category=_memory_category(block.kind),
        token_count=block.estimated_tokens,
        context_kind=_context_kind(block.kind),
    )


def progressive_context_from_delivery(
    delivery: CanonicalContextDeliveryResponse,
) -> ProgressiveContext:
    """Project canonical memory blocks into the legacy ProgressiveContext DTO."""
    context = ProgressiveContext(total_tokens=delivery.estimated_tokens)
    for block in memory_blocks(delivery):
        item = _memory_result(block)
        if block.kind == "mandate":
            context.mandates.append(item)
        elif block.kind == "guardrail":
            context.guardrails.append(item)
        elif block.kind == "capability":
            context.reference_index.append(item)
        else:
            context.reference.append(item)

    context.debug_info.update(canonical_context_debug(delivery))
    context.debug_info.update(
        {
            "reference_selected_count": len(context.reference),
            "reference_selected_uuids": context.get_reference_uuids(),
            "reference_index_count": len(context.reference_index),
            "reference_index_uuids": context.get_reference_index_uuids(),
        }
    )
    return context


def canonical_context_debug(
    delivery: CanonicalContextDeliveryResponse,
) -> dict[str, Any]:
    """Compact immutable audit metadata shared by compatibility surfaces."""
    return {
        "canonical_schema_version": delivery.schema_version,
        "canonical_context_version": delivery.context_version,
        "canonical_delivery_id": delivery.delivery_id,
        "canonical_artifact_id": delivery.artifact_id,
        "canonical_payload_hash": delivery.payload_hash,
        "canonical_block_ids": [block.block_id for block in delivery.blocks],
    }


def canonical_context_contract(
    delivery: CanonicalContextDeliveryResponse,
) -> dict[str, Any]:
    """Public preview/API metadata for cross-surface parity checks."""
    return {
        "schema_version": delivery.schema_version,
        "context_version": delivery.context_version,
        "delivery_id": delivery.delivery_id,
        "artifact_id": delivery.artifact_id,
        "status": delivery.status,
        "payload_hash_algorithm": delivery.payload_hash_algorithm,
        "payload_hash": delivery.payload_hash,
        "delivery_mode": delivery.delivery_mode,
        "recommended_role": delivery.recommended_role,
        "native_context_policy": delivery.native_context_policy,
        "estimated_tokens": delivery.estimated_tokens,
        "block_ids": [block.block_id for block in delivery.blocks],
        "source_ids": [block.provenance.source_id for block in delivery.blocks],
    }


__all__ = [
    "CanonicalContextUnavailable",
    "canonical_context_contract",
    "canonical_context_debug",
    "memory_blocks",
    "progressive_context_from_delivery",
    "require_canonical_context",
]
