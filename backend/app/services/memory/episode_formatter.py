"""Episode formatting utility for memory system.

Central place for all episode formatting logic (DRY principle).
Per research decision (episode-format-decision.md):
- Use Markdown via text source type for rules/standards
- Split by H2 headers; don't store whole files as single episodes
- Source descriptions include metadata for filtering
"""

from datetime import UTC, datetime

from .episode_chunking import chunk_markdown_by_sections
from .episode_helpers import (
    EpisodeOrigin,
    build_declarative_statement,
    build_source_description,
    slugify,
)
from .episode_validation import EpisodeValidator
from .memory_models import FormattedEpisode, InjectionTier
from .service import MemoryCategory, MemoryScope, build_group_id


class EpisodeFormatter:
    """Central formatter for memory episodes."""

    def __init__(self, default_group_id: str = "global"):
        self.default_group_id = default_group_id

    @staticmethod
    def _build_episode_name(
        title: str | None,
        source_file: str | None,
    ) -> str:
        """Derive a deterministic episode name from title or source file."""
        if title:
            return slugify(title)
        if source_file:
            return f"rule_{source_file.replace('.md', '').replace('-', '_')}"
        return f"learning_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    def format_learning(
        self,
        content: str,
        category: MemoryCategory,
        source_file: str | None = None,
        *,
        title: str | None = None,
        tier: InjectionTier = InjectionTier.REFERENCE,
        is_golden: bool = False,
        is_anti_pattern: bool = False,
        confidence: int = 80,
        scope: MemoryScope = MemoryScope.GLOBAL,
        scope_id: str | None = None,
        cluster_id: str | None = None,
        validate: bool = True,
    ) -> FormattedEpisode:
        """Format a learning/rule as a memory episode."""
        if validate:
            EpisodeValidator.validate_content(content)

        name = self._build_episode_name(title, source_file)
        origin = EpisodeOrigin.GOLDEN_STANDARD if is_golden else EpisodeOrigin.RULE_MIGRATION
        source_description = build_source_description(
            category=category,
            tier=tier,
            origin=origin,
            confidence=confidence,
            is_anti_pattern=is_anti_pattern,
            cluster_id=cluster_id,
            source_file=source_file,
        )
        group_id = build_group_id(scope, scope_id)

        return FormattedEpisode(
            name=name,
            episode_body=content,
            source_type="text",
            source_description=source_description,
            reference_time=datetime.now(UTC),
            group_id=group_id,
            category=category,
            scope=scope,
            tier=tier,
            is_golden=is_golden,
            is_anti_pattern=is_anti_pattern,
            confidence=confidence,
        )

    def format_cli_cluster(
        self,
        title: str,
        description: str,
        commands_markdown: str,
        source_file: str,
        cluster_id: str,
        *,
        is_golden: bool = True,
    ) -> FormattedEpisode:
        """Format a CLI command cluster as a memory episode."""
        content = f"# {title}\n\n{description}\n\n{commands_markdown}"

        return self.format_learning(
            content=content,
            category=MemoryCategory.REFERENCE,
            source_file=source_file,
            title=title,
            tier=InjectionTier.REFERENCE,
            is_golden=is_golden,
            is_anti_pattern=False,
            confidence=100 if is_golden else 95,
            cluster_id=cluster_id,
            validate=False,  # CLI clusters use Markdown # headers, not **Topic**: format
        )

    def format_anti_pattern(
        self,
        title: str,
        content: str,
        source_file: str | None = None,
        *,
        cluster_id: str | None = None,
        is_golden: bool = True,
    ) -> FormattedEpisode:
        """Format an anti-pattern as a memory episode."""
        return self.format_learning(
            content=content,
            category=MemoryCategory.GUARDRAIL,
            source_file=source_file,
            title=title,
            tier=InjectionTier.GUARDRAIL,
            is_golden=is_golden,
            is_anti_pattern=True,
            confidence=100 if is_golden else 90,
            cluster_id=cluster_id,
        )

    def format_table_row_as_fact(
        self,
        headers: list[str],
        cells: list[str],
        section_context: str | None = None,
        source_file: str | None = None,
        category: MemoryCategory = MemoryCategory.REFERENCE,
        *,
        is_golden: bool = False,
    ) -> FormattedEpisode | None:
        """Format a markdown table row as a declarative fact.

        Note: Validation is disabled for table row facts because they are
        machine-generated declarative statements (e.g., "Use X instead of Y")
        that don't include the **Topic**: header format. This is intentional
        design, not a workaround - the header requirement exists for
        human-authored content, not machine-extracted table facts.
        """
        statement = build_declarative_statement(headers, cells, section_context, source_file)

        if not statement or len(statement) < 20:
            return None

        is_anti = any(
            h.lower() in ("don't", "dont", "bad", "wrong", "avoid", "never") for h in headers
        )

        return self.format_learning(
            content=statement,
            category=category,
            source_file=source_file,
            tier=InjectionTier.GUARDRAIL if is_anti else InjectionTier.REFERENCE,
            is_golden=is_golden,
            is_anti_pattern=is_anti,
            confidence=100 if is_golden else 80,
            validate=False,
        )

    def chunk_markdown_by_sections(
        self,
        content: str,
        source_file: str,
        category: MemoryCategory,
        *,
        min_chunk_size: int = 50,
    ) -> list[FormattedEpisode]:
        """Split markdown content by H2 headers into separate episodes."""
        return chunk_markdown_by_sections(
            content, source_file, category, self, min_chunk_size=min_chunk_size
        )


# Singleton instance for convenience
_default_formatter: EpisodeFormatter | None = None


def get_episode_formatter() -> EpisodeFormatter:
    """Get the default EpisodeFormatter instance."""
    global _default_formatter
    if _default_formatter is None:
        _default_formatter = EpisodeFormatter()
    return _default_formatter
