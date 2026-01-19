"""Tests for context injector module."""

from datetime import datetime, timezone

import pytest

from app.services.memory.context_injector import (
    CHARS_PER_TOKEN,
    CITATION_INSTRUCTION,
    GUARDRAIL_DIRECTIVE,
    MANDATE_DIRECTIVE,
    REFERENCE_DIRECTIVE,
    ContextTier,
    ProgressiveContext,
    _truncate_by_score,
    estimate_tokens,
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
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="mandate-1", content="m1", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="guardrail-1", content="g1", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
            ],
            reference=[
                MemorySearchResult(
                    uuid="ref-1", content="r1", source=MemorySource.SYSTEM,
                    relevance_score=0.8, created_at=now, facts=[]
                ),
            ],
        )
        uuids = ctx.get_loaded_uuids()
        assert "mandate-1" in uuids
        assert "guardrail-1" in uuids
        assert "ref-1" in uuids
        assert len(uuids) == 3

    def test_get_mandate_uuids(self):
        """Test get_mandate_uuids returns only mandate UUIDs."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1", content="m", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
                MemorySearchResult(
                    uuid="m2", content="m", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1", content="g", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
            ],
        )
        mandate_uuids = ctx.get_mandate_uuids()
        assert mandate_uuids == ["m1", "m2"]

    def test_get_guardrail_uuids(self):
        """Test get_guardrail_uuids returns only guardrail UUIDs."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1", content="m", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1", content="g", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
                MemorySearchResult(
                    uuid="g2", content="g", source=MemorySource.SYSTEM,
                    relevance_score=0.8, created_at=now, facts=[]
                ),
            ],
        )
        guardrail_uuids = ctx.get_guardrail_uuids()
        assert guardrail_uuids == ["g1", "g2"]


class TestContextTier:
    """Tests for ContextTier enum."""

    def test_has_expected_values(self):
        """Test that ContextTier has expected enum values."""
        assert ContextTier.GLOBAL.value == "global"
        assert ContextTier.JIT.value == "jit"
        assert ContextTier.BOTH.value == "both"


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Test empty string returns 0 tokens."""
        assert estimate_tokens("") == 0

    def test_short_string(self):
        """Test short string estimation."""
        # 4 chars per token
        assert estimate_tokens("test") == 1
        assert estimate_tokens("testing") == 1  # 7 chars // 4 = 1
        assert estimate_tokens("testing123") == 2  # 10 chars // 4 = 2

    def test_longer_string(self):
        """Test longer string estimation."""
        # 100 chars / 4 = 25 tokens
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_chars_per_token_constant(self):
        """Test that CHARS_PER_TOKEN is 4."""
        assert CHARS_PER_TOKEN == 4


class TestTruncateByScore:
    """Tests for _truncate_by_score function."""

    def test_empty_list(self):
        """Test empty list returns empty list."""
        assert _truncate_by_score([], 1000) == []

    def test_all_fit_within_limit(self):
        """Test when all items fit within char limit."""
        now = datetime.now(timezone.utc)
        results = [
            MemorySearchResult(
                uuid="1", content="short", source=MemorySource.SYSTEM,
                relevance_score=0.9, created_at=now, facts=[]
            ),
            MemorySearchResult(
                uuid="2", content="also short", source=MemorySource.SYSTEM,
                relevance_score=0.8, created_at=now, facts=[]
            ),
        ]
        truncated = _truncate_by_score(results, 1000)
        assert len(truncated) == 2

    def test_truncates_to_fit_limit(self):
        """Test truncation respects character limit."""
        now = datetime.now(timezone.utc)
        results = [
            MemorySearchResult(
                uuid="1", content="a" * 100, source=MemorySource.SYSTEM,
                relevance_score=0.9, created_at=now, facts=[]
            ),
            MemorySearchResult(
                uuid="2", content="b" * 100, source=MemorySource.SYSTEM,
                relevance_score=0.8, created_at=now, facts=[]
            ),
            MemorySearchResult(
                uuid="3", content="c" * 100, source=MemorySource.SYSTEM,
                relevance_score=0.7, created_at=now, facts=[]
            ),
        ]
        # Max 150 chars should only fit the first item
        truncated = _truncate_by_score(results, 150)
        assert len(truncated) == 1
        assert truncated[0].uuid == "1"

    def test_sorts_by_score_descending(self):
        """Test that results are sorted by score before truncation."""
        now = datetime.now(timezone.utc)
        results = [
            MemorySearchResult(
                uuid="low", content="x" * 50, source=MemorySource.SYSTEM,
                relevance_score=0.5, created_at=now, facts=[]
            ),
            MemorySearchResult(
                uuid="high", content="y" * 50, source=MemorySource.SYSTEM,
                relevance_score=0.95, created_at=now, facts=[]
            ),
            MemorySearchResult(
                uuid="mid", content="z" * 50, source=MemorySource.SYSTEM,
                relevance_score=0.7, created_at=now, facts=[]
            ),
        ]
        # Limit should include high and mid, exclude low
        truncated = _truncate_by_score(results, 120)
        assert len(truncated) == 2
        assert truncated[0].uuid == "high"
        assert truncated[1].uuid == "mid"


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

    def test_task_prefix(self):
        """Test 'task:' prefix returns TASK scope."""
        scope, scope_id = parse_memory_group_id("task:task-123")
        assert scope == MemoryScope.TASK
        assert scope_id == "task-123"

    def test_bare_string_returns_global(self):
        """Test bare string without prefix returns GLOBAL scope."""
        # Per the code: bare strings default to GLOBAL
        scope, scope_id = parse_memory_group_id("some-random-string")
        assert scope == MemoryScope.GLOBAL
        assert scope_id is None


class TestFormatProgressiveContext:
    """Tests for format_progressive_context function."""

    def test_empty_context(self):
        """Test formatting empty context."""
        ctx = ProgressiveContext()
        result = format_progressive_context(ctx)
        assert result == ""

    def test_mandates_only(self):
        """Test formatting context with only mandates."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="abc12345-uuid", content="Always use async", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
        )
        result = format_progressive_context(ctx)
        assert MANDATE_DIRECTIVE in result
        assert "[M:abc12345]" in result
        assert "Always use async" in result
        assert CITATION_INSTRUCTION in result

    def test_guardrails_only(self):
        """Test formatting context with only guardrails."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            guardrails=[
                MemorySearchResult(
                    uuid="def67890-uuid", content="Never use sync calls", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
            ],
        )
        result = format_progressive_context(ctx)
        assert GUARDRAIL_DIRECTIVE in result
        assert "[G:def67890]" in result
        assert "Never use sync calls" in result
        assert CITATION_INSTRUCTION in result

    def test_reference_only(self):
        """Test formatting context with only reference."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            reference=[
                MemorySearchResult(
                    uuid="ref12345-uuid", content="Use this pattern", source=MemorySource.SYSTEM,
                    relevance_score=0.8, created_at=now, facts=[]
                ),
            ],
        )
        result = format_progressive_context(ctx)
        assert REFERENCE_DIRECTIVE in result
        assert "Use this pattern" in result
        # Reference doesn't have citations
        assert "[R:" not in result
        # No citation instruction without mandates/guardrails
        assert CITATION_INSTRUCTION not in result

    def test_all_three_blocks(self):
        """Test formatting context with all three blocks."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid-1234", content="Mandate content", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1-uuid-5678", content="Guardrail content", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
            ],
            reference=[
                MemorySearchResult(
                    uuid="r1-uuid-9012", content="Reference content", source=MemorySource.SYSTEM,
                    relevance_score=0.8, created_at=now, facts=[]
                ),
            ],
        )
        result = format_progressive_context(ctx)

        # Check order: Mandates, Guardrails, Reference
        mandate_pos = result.index(MANDATE_DIRECTIVE)
        guardrail_pos = result.index(GUARDRAIL_DIRECTIVE)
        reference_pos = result.index(REFERENCE_DIRECTIVE)
        assert mandate_pos < guardrail_pos < reference_pos

        # Check all content present
        assert "Mandate content" in result
        assert "Guardrail content" in result
        assert "Reference content" in result

    def test_without_citations(self):
        """Test formatting without citations."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1-uuid", content="Content", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
        )
        result = format_progressive_context(ctx, include_citations=False)
        assert "[M:" not in result
        assert CITATION_INSTRUCTION not in result
        assert "Content" in result


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

    def test_counts_tokens_correctly(self):
        """Test token counting per block."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1", content="a" * 40, source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),  # 40/4 = 10 tokens
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1", content="b" * 20, source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),  # 20/4 = 5 tokens
            ],
            reference=[
                MemorySearchResult(
                    uuid="r1", content="c" * 80, source=MemorySource.SYSTEM,
                    relevance_score=0.8, created_at=now, facts=[]
                ),  # 80/4 = 20 tokens
            ],
        )
        stats = get_context_token_stats(ctx)

        assert stats["mandates_tokens"] == 10
        assert stats["guardrails_tokens"] == 5
        assert stats["reference_tokens"] == 20
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
        """Test that items are formatted with short IDs and snippets."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="12345678-full-uuid-here",
                    content="This is a very long content that should be truncated to 80 characters in the snippet...",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.95,
                    created_at=now,
                    facts=[]
                ),
            ],
            debug_info={"query": "test query"},
        )
        info = get_relevance_debug_info(ctx)

        # Check short ID (first 8 chars)
        assert info["mandates"][0]["id"] == "12345678"
        # Check score rounded
        assert info["mandates"][0]["score"] == 0.95
        # Check snippet truncation (80 chars + ...)
        assert len(info["mandates"][0]["snippet"]) <= 83
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
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1", content="m", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
                ),
            ],
            guardrails=[
                MemorySearchResult(
                    uuid="g1", content="g", source=MemorySource.SYSTEM,
                    relevance_score=0.9, created_at=now, facts=[]
                ),
            ],
            debug_info={"query": "test"},
        )
        result = format_relevance_debug_block(ctx)
        assert "MANDATES:" in result
        assert "GUARDRAILS:" in result

    def test_includes_token_stats(self):
        """Test that token stats are included."""
        now = datetime.now(timezone.utc)
        ctx = ProgressiveContext(
            mandates=[
                MemorySearchResult(
                    uuid="m1", content="test content", source=MemorySource.SYSTEM,
                    relevance_score=1.0, created_at=now, facts=[]
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
        assert REFERENCE_DIRECTIVE == "## Reference"

    def test_citation_instruction(self):
        """Test citation instruction contains citation format."""
        assert "[M:uuid8]" in CITATION_INSTRUCTION
        assert "[G:uuid8]" in CITATION_INSTRUCTION
