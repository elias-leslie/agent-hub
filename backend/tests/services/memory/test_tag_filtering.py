"""Tests for tag-based memory filtering in context_builder.py."""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.context_builder import _apply_tag_filters, filter_by_tags
from app.services.memory.memory_models import (
    MemoryApplicability,
    MemorySearchResult,
    MemorySource,
)


def _make_result(
    uuid: str = "abc-123",
    content: str = "test content",
    tags: list[str] | None = None,
    applicability: MemoryApplicability | None = None,
) -> MemorySearchResult:
    """Create a MemorySearchResult with optional tags."""
    return MemorySearchResult(
        uuid=uuid,
        content=content,
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        facts=[content],
        tags=tags or [],
        applicability=applicability or MemoryApplicability(),
    )


class TestFilterByTags:
    """Tests for filter_by_tags — the core filtering function."""

    def test_no_filters_returns_all(self):
        episodes = [_make_result(uuid="a"), _make_result(uuid="b")]
        result = filter_by_tags(episodes, include_tags=[], exclude_tags=[])
        assert len(result) == 2

    def test_include_filters_by_tag_field(self):
        """include_tags should filter on ep.tags, not content text."""
        tagged = _make_result(uuid="a", content="Some unrelated text", tags=["persona-relevant"])
        untagged = _make_result(uuid="b", content="persona-relevant in content", tags=[])

        result = filter_by_tags([tagged, untagged], include_tags=["persona-relevant"], exclude_tags=[])

        assert len(result) == 1
        assert result[0].uuid == "a"

    def test_exclude_filters_by_tag_field(self):
        """exclude_tags should filter on ep.tags, not content text."""
        tagged = _make_result(uuid="a", content="Some text", tags=["deprecated"])
        clean = _make_result(uuid="b", content="deprecated mentioned in text", tags=[])

        result = filter_by_tags([tagged, clean], include_tags=[], exclude_tags=["deprecated"])

        assert len(result) == 1
        assert result[0].uuid == "b"

    def test_include_and_exclude_combined(self):
        ep1 = _make_result(uuid="a", tags=["persona-relevant"])
        ep2 = _make_result(uuid="b", tags=["persona-relevant", "deprecated"])
        ep3 = _make_result(uuid="c", tags=[])

        result = filter_by_tags(
            [ep1, ep2, ep3],
            include_tags=["persona-relevant"],
            exclude_tags=["deprecated"],
        )

        assert len(result) == 1
        assert result[0].uuid == "a"

    def test_empty_episode_list(self):
        result = filter_by_tags([], include_tags=["foo"], exclude_tags=["bar"])
        assert result == []

    def test_no_matching_include_tag(self):
        ep = _make_result(uuid="a", tags=["other-tag"])
        result = filter_by_tags([ep], include_tags=["persona-relevant"], exclude_tags=[])
        assert len(result) == 0

    def test_multiple_tags_on_episode(self):
        ep = _make_result(uuid="a", tags=["tag1", "tag2", "persona-relevant"])
        result = filter_by_tags([ep], include_tags=["persona-relevant"], exclude_tags=[])
        assert len(result) == 1


class TestApplyTagFilters:
    """Tests for _apply_tag_filters — exclude tags are global, audience tags are legacy-only."""

    def test_legacy_audience_tags_filter_only_untargeted_references(self):
        from app.services.memory.context_builder import ProgressiveContext

        mandate = _make_result(uuid="m1", tags=["persona-relevant"])
        guardrail = _make_result(uuid="g1", tags=["persona-relevant"])
        ref_tagged = _make_result(uuid="r1", tags=["persona-relevant"])
        ref_targeted = _make_result(
            uuid="r2",
            applicability=MemoryApplicability(agent_slugs=["persona"]),
        )
        ref_other = _make_result(uuid="r3", tags=["coder-only"])

        context = ProgressiveContext(
            mandates=[mandate],
            guardrails=[guardrail],
            reference=[ref_tagged, ref_targeted, ref_other],
        )
        memory_config = {"audience_tags": ["persona-relevant"], "exclude_tags": []}

        _apply_tag_filters(context, memory_config)

        assert len(context.mandates) == 1
        assert len(context.guardrails) == 1
        assert [item.uuid for item in context.reference] == ["r1", "r2"]

    def test_exclude_tags_applied_to_all_tiers(self):
        """exclude_tags should filter mandates, guardrails, AND references."""
        from app.services.memory.context_builder import ProgressiveContext

        mandate_bad = _make_result(uuid="m1", tags=["deprecated"])
        mandate_ok = _make_result(uuid="m2", tags=[])
        guardrail_bad = _make_result(uuid="g1", tags=["deprecated"])
        ref_bad = _make_result(uuid="r1", tags=["deprecated"])
        ref_ok = _make_result(uuid="r2", tags=[])

        context = ProgressiveContext(
            mandates=[mandate_bad, mandate_ok],
            guardrails=[guardrail_bad],
            reference=[ref_bad, ref_ok],
        )
        memory_config = {"include_tags": [], "exclude_tags": ["deprecated"]}

        _apply_tag_filters(context, memory_config)

        assert len(context.mandates) == 1
        assert context.mandates[0].uuid == "m2"
        assert len(context.guardrails) == 0
        assert len(context.reference) == 1
        assert context.reference[0].uuid == "r2"

    def test_no_filters_is_noop(self):
        from app.services.memory.context_builder import ProgressiveContext

        context = ProgressiveContext(
            mandates=[_make_result(uuid="m1")],
            guardrails=[_make_result(uuid="g1")],
            reference=[_make_result(uuid="r1")],
        )
        memory_config = {"audience_tags": [], "exclude_tags": []}

        _apply_tag_filters(context, memory_config)

        assert len(context.mandates) == 1
        assert len(context.guardrails) == 1
        assert len(context.reference) == 1
