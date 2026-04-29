"""Tests for context injector module."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.budget import count_tokens
from app.services.memory.context_injector import (
    CHARS_PER_TOKEN,
    CITATION_INSTRUCTION,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    ProgressiveContext,
    extract_query_from_messages,
    format_progressive_context,
    format_relevance_debug_block,
    get_context_token_stats,
    get_relevance_debug_info,
    parse_memory_group_id,
)
from app.services.memory.service import MemoryScope, MemorySearchResult, MemorySource


class TestProgressiveContext:
    """Tests for ProgressiveContext dataclass."""

    def test_empty_context_defaults(self):
        """Test that empty context has sensible defaults."""
        ctx = ProgressiveContext()
        assert ctx.mandates == []
        assert ctx.guardrails == []
        assert ctx.reference == []
        assert ctx.total_tokens == 0
        assert ctx.debug_info == {}

    def test_get_loaded_uuids_empty(self):
        """Test get_loaded_uuids with no items."""
        ctx = ProgressiveContext()
        assert ctx.get_loaded_uuids() == []

    def test_get_loaded_uuids_with_items(self):
        """Test get_loaded_uuids collects all UUIDs."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="mandate-1",
                    content="m1",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="guardrail-1",
                    content="g1",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        uuids = ctx.get_loaded_uuids()
        assert "mandate-1" in uuids
        assert "guardrail-1" in uuids
        assert len(uuids) == 2

    def test_get_mandate_uuids(self):
        """Test get_mandate_uuids returns only mandate UUIDs."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1",
                    content="m",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
                MemorySearchResult(
                    uuid="m2",
                    content="m",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1",
                    content="g",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        mandate_uuids = ctx.get_mandate_uuids()
        assert mandate_uuids == ["m1", "m2"]

    def test_get_guardrail_uuids(self):
        """Test get_guardrail_uuids returns only guardrail UUIDs."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1",
                    content="m",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1",
                    content="g",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
                MemorySearchResult(
                    uuid="g2",
                    content="g",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        guardrail_uuids = ctx.get_guardrail_uuids()
        assert guardrail_uuids == ["g1", "g2"]


class TestCountTokens:
    """Tests for count_tokens function (from budget.py)."""

    def test_empty_string(self):
        """Test empty string returns 0 tokens."""
        assert count_tokens("") == 0

    def test_short_string(self):
        """Test short string estimation."""
        # 4 chars per token
        assert count_tokens("test") == 1
        assert count_tokens("testing") == 1  # 7 chars // 4 = 1
        assert count_tokens("testing123") == 2  # 10 chars // 4 = 2

    def test_longer_string(self):
        """Test longer string estimation."""
        # 100 chars / 4 = 25 tokens
        text = "a" * 100
        assert count_tokens(text) == 25

    def test_chars_per_token_constant(self):
        """Test that CHARS_PER_TOKEN is 4."""
        assert CHARS_PER_TOKEN == 4


class TestParseMemoryGroupId:
    """Tests for parse_memory_group_id function."""

    def test_none_returns_global(self):
        """Test None returns GLOBAL scope."""
        scope, scope_id = parse_memory_group_id(None)
        assert scope == MemoryScope.GLOBAL
        assert scope_id is None

    def test_global_string_returns_global(self):
        """Test 'global' string returns GLOBAL scope."""
        scope, scope_id = parse_memory_group_id("global")
        assert scope == MemoryScope.GLOBAL
        assert scope_id is None

    def test_default_string_returns_global(self):
        """Test 'default' string returns GLOBAL scope."""
        scope, scope_id = parse_memory_group_id("default")
        assert scope == MemoryScope.GLOBAL
        assert scope_id is None

    def test_project_prefix(self):
        """Test 'project:' prefix returns PROJECT scope."""
        scope, scope_id = parse_memory_group_id("project:my-project")
        assert scope == MemoryScope.PROJECT
        assert scope_id == "my-project"

    def test_project_with_complex_id(self):
        """Test project with complex ID."""
        scope, scope_id = parse_memory_group_id("project:org/repo-name")
        assert scope == MemoryScope.PROJECT
        assert scope_id == "org/repo-name"

    def test_bare_string_returns_global(self):
        """Test bare string without prefix returns GLOBAL scope."""
        scope, scope_id = parse_memory_group_id("some-random-string")
        assert scope == MemoryScope.GLOBAL
        assert scope_id is None


class TestExtractQueryFromMessages:
    def test_prefers_task_block_over_wake_guidance(self) -> None:
        query = extract_query_from_messages(
            [
                {
                    "role": "user",
                    "content": (
                        "Operational notes:\n"
                        "- Use known-good commands.\n"
                        "- Avoid broad search first.\n"
                        "Task:\n"
                        "Inspect the agent preview command before coding."
                    ),
                }
            ]
        )

        assert query == "Inspect the agent preview command before coding."

    def test_truncates_task_block_like_runtime_limit(self) -> None:
        query = extract_query_from_messages(
            [{"role": "user", "content": "Task:\n" + ("x" * 900)}]
        )

        assert query == ("x" * 500)


class TestFormatProgressiveContext:
    """Tests for format_progressive_context function."""

    def test_empty_context(self):
        """Test formatting empty context."""
        ctx = ProgressiveContext()
        result = format_progressive_context(ctx)
        assert result == ""

    def test_mandates_only(self):
        """Test formatting context with only mandates."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="abc12345-uuid",
                    content="Always use async",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        result = format_progressive_context(ctx)
        assert MANDATE_DIRECTIVE in result
        assert "[M:abc12345]" in result
        assert "Always use async" in result
        assert CITATION_INSTRUCTION in result
        assert "vague, remembered, or not exact" in result

    def test_guardrails_only(self):
        """Test formatting context with only guardrails."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            guardrails=[
                MemorySearchResult(
                    uuid="def67890-uuid",
                    content="Never use sync calls",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        result = format_progressive_context(ctx)
        assert GUARDRAIL_DIRECTIVE in result
        assert "[G:def67890]" in result
        assert "Never use sync calls" in result
        assert CITATION_INSTRUCTION in result

    def test_both_blocks(self):
        """Test formatting context with mandates and guardrails."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid-1234",
                    content="Mandate content",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1-uuid-5678",
                    content="Guardrail content",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        result = format_progressive_context(ctx)

        # Check order: Mandates, Guardrails
        mandate_pos = result.index(MANDATE_DIRECTIVE)
        guardrail_pos = result.index(GUARDRAIL_DIRECTIVE)
        assert mandate_pos < guardrail_pos

        # Check all content present
        assert "Mandate content" in result
        assert "Guardrail content" in result

    def test_without_citations(self):
        """Test formatting without citations."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid",
                    content="Content",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
        )
        result = format_progressive_context(ctx, include_citations=False)
        assert "[M:" not in result
        assert CITATION_INSTRUCTION not in result
        assert "Content" in result

    def test_prefers_rendered_content_for_tiered_items(self):
        """Tier-aware formatting should inject the planned render text, not always full content."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid",
                    content="Full rule body with detailed rationale and edge-case coverage.",
                    rendered_content="Compact overview of the rule.",
                    render_tier="L1",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
        )

        result = format_progressive_context(ctx)

        assert "Compact overview of the rule." in result
        assert "Full rule body with detailed rationale" not in result

    def test_codex_startup_adds_local_lookup_fallback_line_without_overlay_directive(self):
        """Codex startup keeps the fallback note without adding a separate style overlay."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid",
                    content="Critical startup rule.",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
        )

        result = format_progressive_context(ctx, consumer_profile="codex_startup")

        assert "If local memory lookup is unavailable in this shell" in result
        assert "Terse like caveman." not in result

    def test_agent_runtime_does_not_add_startup_caveman_directive(self):
        """Runtime memory injection should not inherit startup-only output shaping."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid",
                    content="Runtime rule.",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
        )

        result = format_progressive_context(ctx, consumer_profile="agent_runtime")

        assert "Terse like caveman." not in result


class TestGetContextTokenStats:
    """Tests for get_context_token_stats function."""

    def test_empty_context(self):
        """Test stats for empty context."""
        ctx = ProgressiveContext()
        stats = get_context_token_stats(ctx)

        assert stats["mandates_tokens"] == 0
        assert stats["guardrails_tokens"] == 0
        assert stats["reference_tokens"] == 0
        assert stats["mandates_count"] == 0
        assert stats["guardrails_count"] == 0
        assert stats["reference_count"] == 0

    def test_counts_rendered_tokens_and_references(self):
        """Token stats should reflect rendered text for every injected block."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1",
                    content="a" * 80,
                    rendered_content="a" * 20,
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),  # 20/4 = 5 tokens
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1",
                    content="b" * 20,
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),  # 20/4 = 5 tokens
            ],
            reference=[
                MemorySearchResult(
                    uuid="r1",
                    content="c" * 40,
                    rendered_content="c" * 8,
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),  # 8/4 = 2 tokens
            ],
        )
        stats = get_context_token_stats(ctx)

        assert stats["mandates_tokens"] == 5
        assert stats["guardrails_tokens"] == 5
        assert stats["reference_tokens"] == 2
        assert stats["mandates_count"] == 1
        assert stats["guardrails_count"] == 1
        assert stats["reference_count"] == 1


class TestGetRelevanceDebugInfo:
    """Tests for get_relevance_debug_info function."""

    def test_empty_context(self):
        """Test debug info for empty context."""
        ctx = ProgressiveContext()
        info = get_relevance_debug_info(ctx)

        assert info["mandates"] == []
        assert info["guardrails"] == []
        assert info["reference"] == []
        assert "stats" in info

    def test_formats_items_correctly(self):
        """Debug info should use the rendered prompt text and short IDs."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="12345678-full-uuid-here",
                    content="This is a very long content that should be truncated to 80 characters in the snippet...",
                    rendered_content="Rendered snippet should win over the full content.",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.95,
                    created_at=now,
                    facts=[],
                ),
            ],
            debug_info={"query": "test query"},
        )
        info = get_relevance_debug_info(ctx)

        # Check short ID (first 8 chars)
        assert info["mandates"][0]["id"] == "12345678"
        # Check score rounded
        assert info["mandates"][0]["score"] == 0.95
        assert info["mandates"][0]["snippet"] == "Rendered snippet should win over the full content."
        # Check date is just date portion
        assert len(info["mandates"][0]["created"]) == 10


class TestFormatRelevanceDebugBlock:
    """Tests for format_relevance_debug_block function."""

    def test_wraps_in_memory_debug_tags(self):
        """Test that output is wrapped in <memory-debug> tags."""
        ctx = ProgressiveContext()
        result = format_relevance_debug_block(ctx)
        assert result.startswith("<memory-debug>")
        assert result.endswith("</memory-debug>")

    def test_shows_no_memories_message_when_empty(self):
        """Test empty context shows 'No memories matched' message."""
        ctx = ProgressiveContext()
        result = format_relevance_debug_block(ctx)
        assert "No memories matched query" in result

    def test_includes_section_headers(self):
        """Test that section headers are included when items present."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1",
                    content="m",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1",
                    content="g",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
            reference=[
                MemorySearchResult(
                    uuid="r1",
                    content="r",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),
            ],
            debug_info={"query": "test"},
        )
        result = format_relevance_debug_block(ctx)
        assert "MANDATES:" in result
        assert "GUARDRAILS:" in result
        assert "REFERENCES:" in result

    def test_includes_token_stats(self):
        """Test that token stats are included."""
        now = datetime.now(UTC)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1",
                    content="test content",
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,
                    created_at=now,
                    facts=[],
                ),
            ],
            debug_info={"query": "my query"},
        )
        result = format_relevance_debug_block(ctx)
        assert "Tokens:" in result
        assert "Query: my query" in result


class TestDirectiveConstants:
    """Tests for directive constants."""

    def test_directive_values(self):
        """Test that directives have expected values."""
        assert MANDATE_DIRECTIVE == "## Mandates"
        assert GUARDRAIL_DIRECTIVE == "## Guardrails"

    def test_citation_instruction(self):
        """Test citation instruction contains citation format."""
        assert "[M:uuid8]" in CITATION_INSTRUCTION
        assert "[G:uuid8]" in CITATION_INSTRUCTION


class TestInjectionMetrics:
    """Tests for injection metrics collection."""

    def test_injection_metrics_dataclass(self):
        """Test InjectionMetrics dataclass creation."""
        from app.services.memory.metrics_collector import InjectionMetrics

        metrics = InjectionMetrics(
            injection_latency_ms=45,
            mandates_count=5,
            guardrails_count=3,
            reference_count=2,
            reference_selected_count=2,
            reference_index_count=4,
            reference_cited_count=1,
            total_tokens=150,
            query="test query",
            variant="ENHANCED",
            session_id="sess-123",
            external_id="task-456",
            project_id="summitflow",
            memories_loaded=["uuid-1", "uuid-2"],
            reference_selected_uuids=["uuid-1"],
            reference_index_uuids=["uuid-3", "uuid-4"],
        )

        assert metrics.injection_latency_ms == 45
        assert metrics.mandates_count == 5
        assert metrics.guardrails_count == 3
        assert metrics.reference_count == 2
        assert metrics.reference_selected_count == 2
        assert metrics.reference_index_count == 4
        assert metrics.reference_cited_count == 1
        assert metrics.total_tokens == 150
        assert metrics.query == "test query"
        assert metrics.variant == "ENHANCED"
        assert metrics.session_id == "sess-123"
        assert metrics.external_id == "task-456"
        assert metrics.project_id == "summitflow"
        assert metrics.memories_loaded == ["uuid-1", "uuid-2"]
        assert metrics.reference_selected_uuids == ["uuid-1"]
        assert metrics.reference_index_uuids == ["uuid-3", "uuid-4"]

    def test_injection_metrics_defaults(self):
        """Test InjectionMetrics default values."""
        from app.services.memory.metrics_collector import InjectionMetrics

        metrics = InjectionMetrics(
            injection_latency_ms=10,
            mandates_count=0,
            guardrails_count=0,
            reference_count=0,
            total_tokens=0,
        )

        assert metrics.query is None
        assert metrics.variant == "BASELINE"
        assert metrics.session_id is None
        assert metrics.external_id is None
        assert metrics.project_id is None
        assert metrics.memories_loaded is None
        assert metrics.reference_selected_count == 0
        assert metrics.reference_index_count == 0
        assert metrics.reference_cited_count == 0
        assert metrics.reference_selected_uuids is None
        assert metrics.reference_index_uuids is None

    def test_record_injection_metrics_no_loop(self):
        """Test record_injection_metrics handles no event loop gracefully."""
        from app.services.memory.metrics_collector import InjectionMetrics, record_injection_metrics

        metrics = InjectionMetrics(
            injection_latency_ms=10,
            mandates_count=1,
            guardrails_count=1,
            reference_count=1,
            total_tokens=50,
        )

        # Should not raise even without event loop
        record_injection_metrics(metrics)


@pytest.mark.asyncio
async def test_inject_progressive_context_assigns_variant_from_identifiers() -> None:
    from app.services.memory.context_injector_ops import run_injection_operation
    from app.services.memory.settings import MemorySettingsDTO
    from app.services.memory.variants import MemoryVariant

    now = datetime.now(UTC)
    context = ProgressiveContext(
        reference=[
            MemorySearchResult(
                uuid="ref-1",
                content="Reference",
                source=MemorySource.SYSTEM,
                relevance_score=0.8,
                created_at=now,
                facts=[],
            )
        ],
        total_tokens=25,
    )
    settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

    with (
        patch(
            "app.services.memory.context_injector_ops.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.memory.context_injector_ops.build_context_and_format",
            new=AsyncMock(return_value=(context, "formatted")),
        ),
        patch(
            "app.services.memory.context_injector_ops.apply_continuity_to_context",
            new=AsyncMock(return_value="<memory>formatted</memory>"),
        ),
        patch(
            "app.services.memory.context_injector_ops.assign_variant",
            return_value=MemoryVariant.ENHANCED,
        ) as mock_assign,
        patch(
            "app.services.memory.context_injector_ops.resolve_project_index_enabled",
            return_value=False,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_tool_capabilities_enabled",
            return_value=False,
        ),
        patch(
            "app.services.memory.context_injector_ops.record_injection_metrics_for_context",
        ) as mock_metrics,
    ):
        _, injected = await run_injection_operation(
            messages=[{"role": "user", "content": "Need help"}],
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            query="Need help",
            variant=None,
            session_id=None,
            external_id="task-123",
            project_id="agent-hub",
            collect_metrics=True,
            task_type=None,
            phase=None,
            include_continuity=True,
            memory_config=None,
            current_branch=None,
            consumer_profile=None,
            consumer_agent_slug=None,
            consumer_tags=None,
        )

    mock_assign.assert_called_once_with(
        external_id="task-123",
        project_id="agent-hub",
        variant_override=None,
        active_variant=None,
    )
    assert injected.debug_info["variant"] == "ENHANCED"
    assert mock_metrics.call_args.kwargs["variant"] == "ENHANCED"


@pytest.mark.asyncio
async def test_inject_progressive_context_uses_active_variant_before_hash_assignment() -> None:
    from app.services.memory.context_injector_ops import run_injection_operation
    from app.services.memory.settings import MemorySettingsDTO
    from app.services.memory.variants import MemoryVariant

    now = datetime.now(UTC)
    context = ProgressiveContext(
        reference=[
            MemorySearchResult(
                uuid="ref-1",
                content="Reference",
                source=MemorySource.SYSTEM,
                relevance_score=0.8,
                created_at=now,
                facts=[],
            )
        ],
        total_tokens=25,
    )
    settings = MemorySettingsDTO(
        enabled=True,
        budget_enabled=True,
        total_budget=3500,
        active_variant="AGGRESSIVE",
    )

    with (
        patch(
            "app.services.memory.context_injector_ops.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.memory.context_injector_ops.build_context_and_format",
            new=AsyncMock(return_value=(context, "formatted")),
        ),
        patch(
            "app.services.memory.context_injector_ops.apply_continuity_to_context",
            new=AsyncMock(return_value="<memory>formatted</memory>"),
        ),
        patch(
            "app.services.memory.context_injector_ops.assign_variant",
            return_value=MemoryVariant.AGGRESSIVE,
        ) as mock_assign,
        patch(
            "app.services.memory.context_injector_ops.resolve_project_index_enabled",
            return_value=False,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_tool_capabilities_enabled",
            return_value=False,
        ),
        patch(
            "app.services.memory.context_injector_ops.record_injection_metrics_for_context",
        ) as mock_metrics,
    ):
        _, injected = await run_injection_operation(
            messages=[{"role": "user", "content": "Need help"}],
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            query="Need help",
            variant=None,
            session_id=None,
            external_id="task-123",
            project_id="agent-hub",
            collect_metrics=True,
            task_type=None,
            phase=None,
            include_continuity=True,
            memory_config=None,
            current_branch=None,
            consumer_profile=None,
            consumer_agent_slug=None,
            consumer_tags=None,
        )

    mock_assign.assert_called_once_with(
        external_id="task-123",
        project_id="agent-hub",
        variant_override=None,
        active_variant="AGGRESSIVE",
    )
    assert injected.debug_info["variant"] == "AGGRESSIVE"
    assert mock_metrics.call_args.kwargs["variant"] == "AGGRESSIVE"


@pytest.mark.asyncio
async def test_inject_progressive_context_adds_project_index_block_when_enabled() -> None:
    from app.services.memory.context_injector_ops import run_injection_operation
    from app.services.memory.settings import MemorySettingsDTO
    from app.services.memory.variants import MemoryVariant

    settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

    with (
        patch(
            "app.services.memory.context_injector_ops.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.memory.context_injector_ops.build_context_and_format",
            new=AsyncMock(return_value=(ProgressiveContext(total_tokens=0), "")),
        ),
        patch(
            "app.services.memory.context_injector_ops.format_project_index_context",
            return_value="<project-index>\nproject: agent-hub\n</project-index>",
        ),
        patch(
            "app.services.memory.context_injector_ops.assign_variant",
            return_value=MemoryVariant.BASELINE,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_project_index_enabled",
            return_value=True,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_tool_capabilities_enabled",
            return_value=False,
        ),
    ):
        injected_messages, _ = await run_injection_operation(
            messages=[{"role": "user", "content": "Need help"}],
            scope=MemoryScope.PROJECT,
            scope_id="agent-hub",
            query="Need help",
            variant=None,
            session_id=None,
            external_id=None,
            project_id="agent-hub",
            collect_metrics=False,
            task_type=None,
            phase=None,
            include_continuity=False,
            memory_config=None,
            current_branch=None,
            consumer_profile=None,
            consumer_agent_slug=None,
            consumer_tags=None,
        )

    assert injected_messages[0]["role"] == "system"
    assert "<project-index>" in injected_messages[0]["content"]


@pytest.mark.asyncio
async def test_inject_progressive_context_adds_tool_capability_block_when_enabled() -> None:
    from app.services.memory.context_injector_ops import run_injection_operation
    from app.services.memory.settings import MemorySettingsDTO
    from app.services.memory.variants import MemoryVariant

    settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)

    with (
        patch(
            "app.services.memory.context_injector_ops.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.memory.context_injector_ops.build_context_and_format",
            new=AsyncMock(return_value=(ProgressiveContext(total_tokens=0), "")),
        ),
        patch(
            "app.services.memory.context_injector_ops.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.services.memory.context_injector_ops.format_tool_capability_context",
            return_value="<tool-capabilities>\ntools:\n  - tool: st\n</tool-capabilities>",
        ),
        patch(
            "app.services.memory.context_injector_ops.assign_variant",
            return_value=MemoryVariant.BASELINE,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_project_index_enabled",
            return_value=False,
        ),
        patch(
            "app.services.memory.context_injector_ops.resolve_tool_capabilities_enabled",
            return_value=True,
        ),
        patch(
            "app.services.memory.context_injector_ops.get_visible_tools_for_project",
            new=AsyncMock(return_value=frozenset({"bash"})),
        ),
        patch(
            "app.services.memory.context_injector_ops.get_recent_st_usage_memory",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    quick=["st pulse --gate | preflight; edit only if clear"],
                    observed=2,
                )
            ),
        ),
    ):
        injected_messages, context = await run_injection_operation(
            messages=[{"role": "user", "content": "Need help"}],
            scope=MemoryScope.PROJECT,
            scope_id="agent-hub",
            query="Need help",
            variant=None,
            session_id=None,
            external_id=None,
            project_id="agent-hub",
            collect_metrics=False,
            task_type=None,
            phase=None,
            include_continuity=False,
            memory_config=None,
            current_branch=None,
            consumer_profile=None,
            consumer_agent_slug=None,
            consumer_tags=None,
        )

    assert "<tool-capabilities>" in injected_messages[0]["content"]
    assert context.debug_info["tool_capabilities_included"] is True
    assert context.debug_info["st_usage_observed"] == 2
    assert context.debug_info["st_quick_entries"] == 1


@pytest.mark.asyncio
async def test_run_injection_operation_passes_bash_availability_to_tool_capabilities() -> None:
    from app.services.memory.context_injector_ops import run_injection_operation
    from app.services.memory.settings import MemorySettingsDTO
    from app.services.memory.variants import MemoryVariant

    settings = MemorySettingsDTO(enabled=True, budget_enabled=True, total_budget=3500)
    context = ProgressiveContext(total_tokens=0)

    with (
        patch(
            "app.services.memory.context_injector_ops.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.services.memory.context_injector_ops.assign_variant",
            return_value=MemoryVariant.BASELINE,
        ),
        patch(
            "app.services.memory.context_injector_ops.build_context_and_format",
            new=AsyncMock(return_value=(context, "")),
        ),
        patch(
            "app.services.memory.context_injector_ops.format_project_index_context",
            return_value="",
        ),
        patch(
            "app.services.memory.context_injector_ops.get_visible_tools_for_project",
            new=AsyncMock(return_value=frozenset({"read_file"})),
        ) as mock_visible_tools,
        patch(
            "app.services.memory.context_injector_ops.format_tool_capability_context",
            return_value="",
        ) as mock_tool_capabilities,
        patch(
            "app.services.memory.context_injector_ops.finalize_injection",
            new=AsyncMock(return_value=([], context)),
        ),
    ):
        await run_injection_operation(
            messages=[{"role": "user", "content": "Need help"}],
            scope=MemoryScope.PROJECT,
            scope_id="monkey-fight",
            query="Need help",
            variant=None,
            session_id=None,
            external_id=None,
            project_id="monkey-fight",
            collect_metrics=False,
            task_type="wake",
            phase=None,
            include_continuity=False,
            memory_config=None,
            current_branch=None,
            consumer_profile="agent_runtime",
            consumer_agent_slug="persona",
            consumer_tags=None,
        )

    assert mock_visible_tools.await_count == 1
    assert mock_tool_capabilities.call_args is not None
    assert mock_tool_capabilities.call_args.kwargs["bash_available"] is False


@pytest.mark.asyncio
async def test_inject_progressive_context_fails_closed_after_repeated_errors() -> None:
    from app.services.memory.context_injector import inject_progressive_context
    from app.services.memory.context_resilience import MemoryFailureDetails

    failure = MemoryFailureDetails(
        operation="inject-progressive-context",
        attempts=3,
        error_type="RuntimeError",
        error_message="neo4j restart in progress",
        latency_ms=123,
    )

    with (
        patch(
            "app.services.memory.context_injector._run_injection_with_retries",
            new=AsyncMock(return_value=(None, failure, 3, 123)),
        ),
        patch(
            "app.services.memory.context_injector_ops.report_memory_failure",
            new=AsyncMock(),
        ) as mock_report,
    ):
        injected_messages, context = await inject_progressive_context(
            messages=[{"role": "user", "content": "Need help"}],
            project_id="agent-hub",
            scope=MemoryScope.PROJECT,
            scope_id="agent-hub",
            consumer_profile="claude_session_start",
        )

    assert mock_report.await_count == 1
    assert injected_messages[0]["role"] == "system"
    assert "CRITICAL" in injected_messages[0]["content"]
    assert "Stop substantive work immediately" in injected_messages[0]["content"]
    assert "st memory status" in injected_messages[0]["content"]
    assert context.debug_info["memory_system_failed"] is True
    assert context.debug_info["failure_mode"] == "stop"
