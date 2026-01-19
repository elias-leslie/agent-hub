"""Tests for episode formatter module."""

import pytest

from app.services.memory.episode_formatter import (
    EpisodeFormatter,
    EpisodeOrigin,
    FormattedEpisode,
    InjectionTier,
    get_episode_formatter,
)
from app.services.memory.service import MemoryCategory, MemoryScope


class TestInjectionTier:
    """Tests for InjectionTier enum."""

    def test_has_expected_values(self):
        """Test that InjectionTier has expected enum values."""
        assert InjectionTier.MANDATE.value == "mandate"
        assert InjectionTier.GUARDRAIL.value == "guardrail"
        assert InjectionTier.REFERENCE.value == "reference"


class TestEpisodeOrigin:
    """Tests for EpisodeOrigin enum."""

    def test_has_expected_values(self):
        """Test that EpisodeOrigin has expected enum values."""
        assert EpisodeOrigin.RULE_MIGRATION.value == "rule_migration"
        assert EpisodeOrigin.GOLDEN_STANDARD.value == "golden_standard"
        assert EpisodeOrigin.LEARNING.value == "learning"
        assert EpisodeOrigin.USER.value == "user"


class TestEpisodeFormatterSlugify:
    """Tests for EpisodeFormatter._slugify method."""

    def test_lowercases_text(self):
        """Test that text is lowercased."""
        formatter = EpisodeFormatter()
        assert formatter._slugify("HELLO") == "hello"
        assert formatter._slugify("HeLLo WoRLd") == "hello_world"

    def test_removes_special_characters(self):
        """Test that special characters are removed (not replaced with underscore)."""
        formatter = EpisodeFormatter()
        # Special chars are removed, not replaced
        assert formatter._slugify("hello@world!") == "helloworld"
        assert formatter._slugify("test#$%test") == "testtest"

    def test_converts_spaces_to_underscores(self):
        """Test that spaces become underscores."""
        formatter = EpisodeFormatter()
        assert formatter._slugify("hello world") == "hello_world"
        assert formatter._slugify("multiple   spaces") == "multiple_spaces"

    def test_limits_length_to_50(self):
        """Test that slug is limited to 50 characters."""
        formatter = EpisodeFormatter()
        long_text = "a" * 100
        result = formatter._slugify(long_text)
        assert len(result) == 50

    def test_preserves_dashes(self):
        """Test that dashes are preserved."""
        formatter = EpisodeFormatter()
        assert formatter._slugify("hello-world") == "hello-world"


class TestEpisodeFormatterBuildSourceDescription:
    """Tests for EpisodeFormatter._build_source_description method."""

    def test_basic_description(self):
        """Test basic source description format."""
        formatter = EpisodeFormatter()
        desc = formatter._build_source_description(
            category=MemoryCategory.CODING_STANDARD,
            tier=InjectionTier.REFERENCE,
            origin=EpisodeOrigin.RULE_MIGRATION,
            confidence=80,
        )
        assert "coding_standard" in desc
        assert "reference" in desc
        assert "source:rule_migration" in desc
        assert "confidence:80" in desc

    def test_includes_anti_pattern_marker(self):
        """Test anti-pattern marker is included when flagged."""
        formatter = EpisodeFormatter()
        desc = formatter._build_source_description(
            category=MemoryCategory.TROUBLESHOOTING_GUIDE,
            tier=InjectionTier.GUARDRAIL,
            origin=EpisodeOrigin.GOLDEN_STANDARD,
            confidence=100,
            is_anti_pattern=True,
        )
        assert "type:anti_pattern" in desc

    def test_includes_cluster_id(self):
        """Test cluster ID is included when provided."""
        formatter = EpisodeFormatter()
        desc = formatter._build_source_description(
            category=MemoryCategory.OPERATIONAL_CONTEXT,
            tier=InjectionTier.REFERENCE,
            origin=EpisodeOrigin.RULE_MIGRATION,
            confidence=95,
            cluster_id="cli_commands",
        )
        assert "cluster:cli_commands" in desc

    def test_includes_source_file(self):
        """Test source file is included when provided."""
        formatter = EpisodeFormatter()
        desc = formatter._build_source_description(
            category=MemoryCategory.CODING_STANDARD,
            tier=InjectionTier.MANDATE,
            origin=EpisodeOrigin.RULE_MIGRATION,
            confidence=100,
            source_file="dev-standards.md",
        )
        assert "migrated_from:dev-standards.md" in desc

    def test_all_optional_fields(self):
        """Test all optional fields together."""
        formatter = EpisodeFormatter()
        desc = formatter._build_source_description(
            category=MemoryCategory.TROUBLESHOOTING_GUIDE,
            tier=InjectionTier.GUARDRAIL,
            origin=EpisodeOrigin.GOLDEN_STANDARD,
            confidence=100,
            is_anti_pattern=True,
            cluster_id="gotchas",
            source_file="pitfalls.md",
        )
        assert "troubleshooting_guide" in desc
        assert "guardrail" in desc
        assert "source:golden_standard" in desc
        assert "confidence:100" in desc
        assert "type:anti_pattern" in desc
        assert "cluster:gotchas" in desc
        assert "migrated_from:pitfalls.md" in desc


class TestEpisodeFormatterBuildDeclarativeStatement:
    """Tests for EpisodeFormatter._build_declarative_statement method."""

    def test_do_dont_pattern(self):
        """Test Do/Don't table conversion."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Do", "Don't"],
            cells=["async methods", "sync methods"],
            section_context=None,
            source_file=None,
        )
        assert statement == "Use async methods instead of sync methods."

    def test_dont_do_pattern_reversed(self):
        """Test Don't/Do table (reversed order) conversion."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Don't", "Do Instead"],
            cells=["sync calls", "async calls"],
            section_context=None,
            source_file=None,
        )
        assert statement == "Use async calls instead of sync calls."

    def test_command_description_pattern(self):
        """Test Command/Description table conversion."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Command", "Description"],
            cells=["st ready", "Shows available tasks"],
            section_context=None,
            source_file=None,
        )
        assert statement == "The 'st ready' command shows available tasks."

    def test_flag_action_pattern(self):
        """Test Flag/Action table conversion."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Flag", "Action"],
            cells=["--verbose", "Enables verbose output"],
            section_context=None,
            source_file=None,
        )
        assert statement == "The '--verbose' flag enables verbose output."

    def test_error_fix_pattern(self):
        """Test Error/Fix table conversion."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Error", "Fix"],
            cells=["Connection timeout", "Increase timeout value"],
            section_context=None,
            source_file=None,
        )
        assert statement == "When encountering 'Connection timeout', increase timeout value."

    def test_generic_pattern_with_context(self):
        """Test generic pattern includes source file context."""
        formatter = EpisodeFormatter()
        statement = formatter._build_declarative_statement(
            headers=["Item", "Value"],
            cells=["Setting A", "Config B"],
            section_context="Configuration",
            source_file="settings.md",
        )
        assert "settings.md:" in statement
        assert "(Configuration)" in statement
        assert "Setting A relates to Config B" in statement

    def test_returns_empty_for_insufficient_headers(self):
        """Test returns empty string for insufficient headers."""
        formatter = EpisodeFormatter()
        assert formatter._build_declarative_statement(["Only"], ["One"], None, None) == ""

    def test_returns_empty_for_insufficient_cells(self):
        """Test returns empty string for insufficient cells."""
        formatter = EpisodeFormatter()
        assert formatter._build_declarative_statement(["H1", "H2"], ["One"], None, None) == ""

    def test_returns_empty_for_empty_cells(self):
        """Test returns empty for empty cell values."""
        formatter = EpisodeFormatter()
        assert formatter._build_declarative_statement(["H1", "H2"], ["", ""], None, None) == ""


class TestEpisodeFormatterGetGroupId:
    """Tests for EpisodeFormatter._get_group_id method."""

    def test_global_scope(self):
        """Test GLOBAL scope returns 'global'."""
        formatter = EpisodeFormatter()
        assert formatter._get_group_id(MemoryScope.GLOBAL, None) == "global"
        assert formatter._get_group_id(MemoryScope.GLOBAL, "ignored") == "global"

    def test_project_scope(self):
        """Test PROJECT scope returns 'project-{id}'."""
        formatter = EpisodeFormatter()
        assert formatter._get_group_id(MemoryScope.PROJECT, "my-proj") == "project-my-proj"

    def test_task_scope(self):
        """Test TASK scope returns 'task-{id}'."""
        formatter = EpisodeFormatter()
        assert formatter._get_group_id(MemoryScope.TASK, "task-123") == "task-task-123"

    def test_default_scope_id(self):
        """Test missing scope_id uses 'default'."""
        formatter = EpisodeFormatter()
        assert formatter._get_group_id(MemoryScope.PROJECT, None) == "project-default"


class TestEpisodeFormatterFormatLearning:
    """Tests for EpisodeFormatter.format_learning method."""

    def test_basic_learning(self):
        """Test basic learning formatting."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Always use async methods",
            category=MemoryCategory.CODING_STANDARD,
        )

        assert isinstance(episode, FormattedEpisode)
        assert episode.episode_body == "Always use async methods"
        assert episode.category == MemoryCategory.CODING_STANDARD
        assert episode.scope == MemoryScope.GLOBAL
        assert episode.group_id == "global"
        assert episode.tier == InjectionTier.REFERENCE  # default
        assert not episode.is_golden  # default
        assert episode.confidence == 80  # default

    def test_golden_learning(self):
        """Test golden standard learning."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Critical rule",
            category=MemoryCategory.SYSTEM_DESIGN,
            is_golden=True,
            tier=InjectionTier.MANDATE,
            confidence=100,
        )

        assert episode.is_golden
        assert episode.tier == InjectionTier.MANDATE
        assert episode.confidence == 100
        assert "golden_standard" in episode.source_description

    def test_anti_pattern_learning(self):
        """Test anti-pattern learning."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Don't use sync calls",
            category=MemoryCategory.TROUBLESHOOTING_GUIDE,
            is_anti_pattern=True,
            tier=InjectionTier.GUARDRAIL,
        )

        assert episode.is_anti_pattern
        assert episode.tier == InjectionTier.GUARDRAIL
        assert "anti_pattern" in episode.source_description

    def test_learning_with_title(self):
        """Test learning with custom title generates correct name."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Content here",
            category=MemoryCategory.CODING_STANDARD,
            title="My Custom Title",
        )

        assert episode.name == "my_custom_title"

    def test_learning_with_source_file(self):
        """Test learning with source file generates correct name."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Content here",
            category=MemoryCategory.CODING_STANDARD,
            source_file="dev-standards.md",
        )

        assert episode.name == "rule_dev_standards"
        assert "migrated_from:dev-standards.md" in episode.source_description

    def test_learning_with_project_scope(self):
        """Test learning with project scope."""
        formatter = EpisodeFormatter()
        episode = formatter.format_learning(
            content="Project specific rule",
            category=MemoryCategory.DOMAIN_KNOWLEDGE,
            scope=MemoryScope.PROJECT,
            scope_id="my-project",
        )

        assert episode.scope == MemoryScope.PROJECT
        assert episode.group_id == "project-my-project"


class TestEpisodeFormatterFormatCliCluster:
    """Tests for EpisodeFormatter.format_cli_cluster method."""

    def test_formats_cli_cluster(self):
        """Test CLI cluster formatting."""
        formatter = EpisodeFormatter()
        episode = formatter.format_cli_cluster(
            title="st CLI: Active Workflow",
            description="Day-to-day task execution commands",
            commands_markdown="| Command | Description |\n| --- | --- |",
            source_file="st-cli.md",
            cluster_id="active_workflow",
        )

        assert "# st CLI: Active Workflow" in episode.episode_body
        assert "Day-to-day task execution commands" in episode.episode_body
        assert episode.category == MemoryCategory.OPERATIONAL_CONTEXT
        assert episode.tier == InjectionTier.REFERENCE
        assert episode.is_golden
        assert "cluster:active_workflow" in episode.source_description


class TestEpisodeFormatterFormatAntiPattern:
    """Tests for EpisodeFormatter.format_anti_pattern method."""

    def test_formats_anti_pattern(self):
        """Test anti-pattern formatting."""
        formatter = EpisodeFormatter()
        episode = formatter.format_anti_pattern(
            title="Avoid Sync Calls",
            content="Never use synchronous I/O in async context",
        )

        assert episode.category == MemoryCategory.TROUBLESHOOTING_GUIDE
        assert episode.tier == InjectionTier.GUARDRAIL
        assert episode.is_anti_pattern
        assert episode.is_golden  # default
        assert "anti_pattern" in episode.source_description


class TestEpisodeFormatterFormatTableRowAsFact:
    """Tests for EpisodeFormatter.format_table_row_as_fact method."""

    def test_formats_do_dont_row(self):
        """Test formatting a Do/Don't table row."""
        formatter = EpisodeFormatter()
        episode = formatter.format_table_row_as_fact(
            headers=["Do", "Don't"],
            cells=["async methods", "sync methods"],
        )

        assert episode is not None
        assert "Use async methods instead of sync methods" in episode.episode_body
        assert episode.tier == InjectionTier.GUARDRAIL  # Has "Don't" header

    def test_returns_none_for_trivial_row(self):
        """Test returns None for trivial content."""
        formatter = EpisodeFormatter()
        episode = formatter.format_table_row_as_fact(
            headers=["Do", "Don't"],
            cells=["x", "y"],  # Too short
        )

        assert episode is None

    def test_detects_anti_pattern_from_headers(self):
        """Test anti-pattern detection from Don't headers."""
        formatter = EpisodeFormatter()
        # Use standard "Do"/"Don't" headers which explicitly trigger anti-pattern
        episode = formatter.format_table_row_as_fact(
            headers=["Don't", "Do"],
            cells=["use eval() for user input", "use safe parsing methods"],
        )

        # "Don't" header triggers anti-pattern detection
        if episode is not None:
            assert episode.is_anti_pattern
            assert episode.tier == InjectionTier.GUARDRAIL


class TestEpisodeFormatterChunkMarkdownBySections:
    """Tests for EpisodeFormatter.chunk_markdown_by_sections method."""

    def test_splits_by_h2_headers(self):
        """Test markdown is split by H2 headers."""
        formatter = EpisodeFormatter()
        # Content needs to be > 50 chars (default min_chunk_size) per section
        content = """# Top Header

## Section One

This is the content for section one. It needs to be long enough to exceed the minimum chunk size of 50 characters.

## Section Two

This is the content for section two. It also needs to be long enough to exceed the minimum chunk size of 50 characters.
"""
        episodes = formatter.chunk_markdown_by_sections(
            content=content,
            source_file="test.md",
            category=MemoryCategory.CODING_STANDARD,
        )

        assert len(episodes) >= 2
        # Check section titles are used as names
        names = [ep.name for ep in episodes]
        assert any("section_one" in name for name in names)
        assert any("section_two" in name for name in names)

    def test_skips_small_sections(self):
        """Test small sections are skipped."""
        formatter = EpisodeFormatter()
        content = """## Tiny

X

## Normal Section

This section has enough content to be included in the results because it exceeds the minimum chunk size threshold.
"""
        episodes = formatter.chunk_markdown_by_sections(
            content=content,
            source_file="test.md",
            category=MemoryCategory.CODING_STANDARD,
            min_chunk_size=30,  # Tiny section is ~10 chars, Normal is > 30
        )

        # Only the normal section should be included
        assert len(episodes) == 1
        assert "Normal Section" in episodes[0].episode_body

    def test_detects_anti_patterns_in_sections(self):
        """Test anti-pattern detection in sections."""
        formatter = EpisodeFormatter()
        # Content needs to exceed min_chunk_size (50)
        content = """## Anti-Patterns to Avoid

Never do this bad thing. This section contains guidance on anti-patterns and things to avoid in your code.

## Best Practices

Always do this good thing. This section contains positive guidance on best practices to follow in your codebase.
"""
        episodes = formatter.chunk_markdown_by_sections(
            content=content,
            source_file="test.md",
            category=MemoryCategory.CODING_STANDARD,
        )

        # Find the anti-pattern section (contains "anti-pattern" and "avoid")
        anti_pattern_eps = [ep for ep in episodes if ep.is_anti_pattern]
        good_eps = [ep for ep in episodes if not ep.is_anti_pattern]

        assert len(anti_pattern_eps) >= 1
        assert len(good_eps) >= 1


class TestGetEpisodeFormatter:
    """Tests for get_episode_formatter singleton."""

    def test_returns_episode_formatter(self):
        """Test returns an EpisodeFormatter instance."""
        formatter = get_episode_formatter()
        assert isinstance(formatter, EpisodeFormatter)

    def test_returns_same_instance(self):
        """Test returns the same instance (singleton)."""
        formatter1 = get_episode_formatter()
        formatter2 = get_episode_formatter()
        assert formatter1 is formatter2


class TestFormattedEpisode:
    """Tests for FormattedEpisode dataclass."""

    def test_has_required_fields(self):
        """Test FormattedEpisode has all required fields."""
        from datetime import datetime, timezone
        from graphiti_core.nodes import EpisodeType

        episode = FormattedEpisode(
            name="test_episode",
            episode_body="Test content",
            source_type=EpisodeType.text,
            source_description="test description",
            reference_time=datetime.now(timezone.utc),
            group_id="global",
            category=MemoryCategory.CODING_STANDARD,
            scope=MemoryScope.GLOBAL,
            tier=InjectionTier.REFERENCE,
            is_golden=False,
            is_anti_pattern=False,
            confidence=80,
        )

        assert episode.name == "test_episode"
        assert episode.episode_body == "Test content"
        assert episode.group_id == "global"
        assert episode.confidence == 80
