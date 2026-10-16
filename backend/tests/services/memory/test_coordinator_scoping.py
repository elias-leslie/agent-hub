"""Coordinator-only memories reach only sessions tagged aico-coordinator."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.applicability import (
    ROLE_CONSUMER_TAGS,
    applicability_matches,
    legacy_routing_tags,
)
from app.services.memory.context_builder import (
    ProgressiveContext,
    _apply_applicability_filters,
    _apply_tag_filters,
)
from app.services.memory.memory_models import (
    MemoryApplicability,
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.runtime_context import _forced_memory_item_matches

COORDINATOR = "aico-coordinator"


def _memory(uuid: str, *, category: MemoryCategory, coordinator_only: bool = False, tags: list[str] | None = None) -> MemorySearchResult:
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
        applicability=MemoryApplicability(audience_tags=[COORDINATOR] if coordinator_only else []),
    )


def test_coordinator_tag_is_a_role_tag() -> None:
    assert COORDINATOR in ROLE_CONSUMER_TAGS
    assert legacy_routing_tags([COORDINATOR, "operator"]) == ["operator"]


def test_coordinator_applicability_matches_only_coordinators() -> None:
    targeted = MemoryApplicability(audience_tags=[COORDINATOR])
    assert applicability_matches(targeted, consumer_surface="claude_code", consumer_tags=[COORDINATOR])
    assert not applicability_matches(targeted, consumer_surface="claude_code", consumer_tags=[])
    assert not applicability_matches(targeted, consumer_surface="codex", consumer_tags=None)


def _context() -> ProgressiveContext:
    return ProgressiveContext(
        guardrails=[
            _memory("coord", category=MemoryCategory.GUARDRAIL, coordinator_only=True),
            _memory("plain", category=MemoryCategory.GUARDRAIL),
        ],
        reference=[_memory("legacy-ref", category=MemoryCategory.REFERENCE, tags=["topic"])],
    )


def _filter(context: ProgressiveContext, tags: list[str]) -> ProgressiveContext:
    _apply_tag_filters(context, {"audience_tags": tags, "exclude_tags": []})
    _apply_applicability_filters(
        context,
        consumer_surface="claude_code",
        consumer_profile="agent_startup",
        consumer_agent_slug=None,
        consumer_tags=tags,
    )
    return context


def test_plain_session_gets_no_coordinator_guardrail() -> None:
    context = _filter(_context(), [])
    assert [item.uuid for item in context.guardrails] == ["plain"]
    assert [item.uuid for item in context.reference] == ["legacy-ref"]


def test_coordinator_gets_guardrail_and_keeps_legacy_references() -> None:
    context = _filter(_context(), [COORDINATOR])
    assert [item.uuid for item in context.guardrails] == ["coord", "plain"]
    assert [item.uuid for item in context.reference] == ["legacy-ref"]


def test_topic_tags_still_route_legacy_references() -> None:
    context = _filter(_context(), [COORDINATOR, "other-topic"])
    assert context.reference == []


def _forced(item: MemorySearchResult, tags: list[str]) -> bool:
    return _forced_memory_item_matches(
        item,
        project_id=None,
        include_global=True,
        include_mandates=True,
        include_guardrails=True,
        include_references=True,
        exclude_tags=[],
        exclude_memory_uuids=[],
        consumer_surface="claude_code",
        consumer_profile="agent_startup",
        consumer_agent_slug=None,
        consumer_tags=tags,
    )


def test_forced_items_follow_the_same_role_rules() -> None:
    coordinator_only = _memory("coord", category=MemoryCategory.GUARDRAIL, coordinator_only=True)
    legacy_ref = _memory("legacy-ref", category=MemoryCategory.REFERENCE, tags=["topic"])
    assert not _forced(coordinator_only, [])
    assert _forced(coordinator_only, [COORDINATOR])
    assert _forced(legacy_ref, [COORDINATOR])
    assert not _forced(legacy_ref, [COORDINATOR, "other-topic"])


def test_coordinator_bootstrap_pointer_reaches_only_plain_sessions() -> None:
    """A session is flagged coordinator only after its first lane, and context is
    computed at launch, so the pointer to the coordinator rules must reach plain
    sessions (and may skip sessions that already get the full rules)."""
    bootstrap = _memory("bootstrap", category=MemoryCategory.GUARDRAIL)
    bootstrap.applicability = MemoryApplicability(exclude_audience_tags=[COORDINATOR])
    for tags, expected in (([], ["plain", "bootstrap"]), ([COORDINATOR], ["coord", "plain"])):
        context = _context()
        context.guardrails.append(bootstrap)
        assert [item.uuid for item in _filter(context, tags).guardrails] == expected
