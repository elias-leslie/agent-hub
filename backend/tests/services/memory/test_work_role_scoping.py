"""Declared work roles select context through `work-role:<id>` audience tags."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.applicability import (
    ROLE_CONSUMER_TAGS,
    UNKNOWN_ROLE_TAG,
    applicability_matches,
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


# Coordinator-only rules reach coordinators and sessions whose role is not
# known, never a session that declared a narrower role.
COORDINATOR_OR_UNKNOWN = MemoryApplicability(
    audience_tags=["aico-coordinator", "work-role:coordinator", UNKNOWN_ROLE_TAG]
)


def test_coordinator_rules_reach_coordinators_and_unknown_roles_only() -> None:
    for tags, expected in (
        ([], True),
        (["topic"], True),
        (["aico-coordinator"], True),
        (["work-role:coordinator"], True),
        (["aico-coordinator", "work-role:implementation"], True),
        ([RECON], False),
        ([REVIEW], False),
        (["work-role:verification"], False),
        (["work-role:implementation", "topic"], False),
    ):
        assert applicability_matches(COORDINATOR_OR_UNKNOWN, consumer_tags=tags) is expected, tags


def test_unknown_role_tag_cannot_be_supplied_by_a_caller() -> None:
    # A declared role wins over a forged unknown tag.
    assert not applicability_matches(COORDINATOR_OR_UNKNOWN, consumer_tags=[UNKNOWN_ROLE_TAG, REVIEW])
    # It is not a registered role, so canonical requests drop it.
    assert normalize_consumer_tags([UNKNOWN_ROLE_TAG, REVIEW]) == [REVIEW]
    # Excluding unknown roles keeps declared ones.
    excluded = MemoryApplicability(exclude_audience_tags=[UNKNOWN_ROLE_TAG])
    assert not applicability_matches(excluded, consumer_tags=[])
    assert applicability_matches(excluded, consumer_tags=[REVIEW])
