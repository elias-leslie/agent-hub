"""Declared work roles select context through `work-role:<id>` audience tags."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.applicability import (
    ROLE_CONSUMER_TAGS,
    legacy_routing_tags,
    normalize_consumer_tags,
)
from app.services.memory.context_builder import ProgressiveContext, _apply_all_filters
from app.services.memory.memory_models import (
    MemoryApplicability,
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    _normalize_canonical_request,
)
from app.services.session_roles import WORK_ROLES

RECON = "work-role:recon"
REVIEW = "work-role:review"


def _memory(uuid: str, category: MemoryCategory, applicability: MemoryApplicability | None = None,
            tags: list[str] | None = None) -> MemorySearchResult:
    return MemorySearchResult(
        uuid=uuid,
        content=uuid,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        facts=[uuid],
        tags=tags or [],
        scope=MemoryScope.GLOBAL,
        category=category,
        applicability=applicability or MemoryApplicability(),
    )


def _select(tags: list[str]) -> ProgressiveContext:
    context = ProgressiveContext(
        guardrails=[
            _memory("plain", MemoryCategory.GUARDRAIL),
            _memory("not-recon", MemoryCategory.GUARDRAIL,
                    MemoryApplicability(exclude_audience_tags=[RECON])),
            _memory("review-only", MemoryCategory.GUARDRAIL, MemoryApplicability(audience_tags=[REVIEW])),
        ],
        reference=[_memory("legacy-ref", MemoryCategory.REFERENCE, tags=["topic"])],
    )
    _apply_all_filters(
        context,
        {"audience_tags": tags, "exclude_tags": []},
        consumer_surface="pi",
        consumer_profile="agent_startup",
        consumer_agent_slug=None,
        consumer_tags=tags,
    )
    return context


def test_every_registered_work_role_is_a_role_tag() -> None:
    assert {f"work-role:{role}" for role in WORK_ROLES} <= ROLE_CONSUMER_TAGS
    assert legacy_routing_tags([RECON, "topic"]) == ["topic"]


def test_unregistered_work_role_tags_are_dropped() -> None:
    assert normalize_consumer_tags([" Work-Role:Recon ", "work-role:bogus", "topic", RECON, ""]) == [
        RECON,
        "topic",
    ]
    request = _normalize_canonical_request(
        CanonicalContextDeliveryRequest(consumer_surface="pi", consumer_tags=["work-role:bogus", REVIEW])
    )
    assert request.consumer_tags == [REVIEW]


def test_required_policy_follows_role_applicability() -> None:
    for tags, expected in (
        ([RECON], ["plain"]),
        ([REVIEW], ["plain", "not-recon", "review-only"]),
        # No declared role keeps every exclusion-scoped rule.
        ([], ["plain", "not-recon"]),
    ):
        context = _select(tags)
        assert [item.uuid for item in context.guardrails] == expected
        # Verification expects exactly the applicable required rules.
        assert context.debug_info["expected_required_memory_ids"] == expected


def test_role_tag_keeps_untargeted_references() -> None:
    assert [item.uuid for item in _select([RECON]).reference] == ["legacy-ref"]
