"""
Episode formatting utility for Graphiti knowledge graph.

Central place for all episode formatting logic (DRY principle).
Per research decision (episode-format-decision.md):
- Use Markdown via EpisodeType.text for rules/standards
- Split by H2 headers, don't store whole files as single episodes
- Source descriptions include metadata for filtering

Usage:
    from app.services.memory.episode_formatter import EpisodeFormatter

    formatter = EpisodeFormatter()

    # Format a learning/rule
    episode = formatter.format_learning(
        content="## Variable Naming\n| Do | Don't |\n...",
        category=MemoryCategory.REFERENCE,
        source_file="dev-standards.md",
        is_golden=True,
    )

    # Format a CLI reference cluster
    episode = formatter.format_cli_cluster(
        title="Active Workflow Commands",
        description="Day-to-day task execution commands",
        commands_markdown="| Command | Description |\n...",
        source_file="st-cli.md",
        cluster_id="active_workflow",
    )
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import ClassVar

from graphiti_core.nodes import EpisodeType

from .service import MemoryCategory, MemoryScope, build_group_id


class EpisodeValidationError(Exception):
    """Raised when episode content fails validation."""

    def __init__(self, message: str, detected_patterns: list[str]):
        self.message = message
        self.detected_patterns = detected_patterns
        super().__init__(message)


class InjectionTier(str, Enum):
    """Injection tier for progressive disclosure."""

    MANDATE = "mandate"  # Always inject (critical constraints, golden standards)
    GUARDRAIL = "guardrail"  # Type-filtered (anti-patterns, gotchas)
    REFERENCE = "reference"  # Semantic search (patterns, workflows)


class EpisodeOrigin(str, Enum):
    """Source origin for episodes."""

    RULE_MIGRATION = "rule_migration"  # Migrated from rules files
    GOLDEN_STANDARD = "golden_standard"  # Curated golden standard
    LEARNING = "learning"  # Runtime learning from sessions
    USER = "user"  # User-provided preference/rule


@dataclass
class FormattedEpisode:
    """Formatted episode ready for Graphiti ingestion."""

    name: str
    episode_body: str
    source_type: EpisodeType
    source_description: str
    reference_time: datetime
    group_id: str
    # Metadata for tracking (not sent to Graphiti directly)
    category: MemoryCategory
    scope: MemoryScope
    tier: InjectionTier
    is_golden: bool
    is_anti_pattern: bool
    confidence: int  # 0-100


class EpisodeFormatter:
    """
    Central formatter for Graphiti episodes.

    Implements the episode format decision:
    - Markdown via EpisodeType.text for rules/standards
    - Consistent source descriptions with metadata
    - Proper chunking and naming
    """

    # Verbose patterns that indicate conversational/verbose content
    VERBOSE_PATTERNS: ClassVar[list[str]] = [
        "you should",
        "i recommend",
        "please",
        "thank you",
        "let me know",
        "feel free",
        "i suggest",
        "you might want",
        "consider using",
        "it would be",
        "it's important to",
    ]

    def __init__(self, default_group_id: str = "global"):
        self.default_group_id = default_group_id

    def validate_content(self, content: str) -> None:
        """
        Validate episode content for conciseness and declarative style.

        Rejects verbose, conversational content that indicates the agent
        is not writing correctly the first time.

        Args:
            content: Episode content to validate

        Raises:
            EpisodeValidationError: If content contains verbose patterns
        """
        detected = []
        content_lower = content.lower()

        for pattern in self.VERBOSE_PATTERNS:
            if pattern in content_lower:
                detected.append(pattern)

        if detected:
            raise EpisodeValidationError(
                message=f"Episode content is too verbose. "
                f"Write declarative facts, not conversational advice. "
                f"Detected patterns: {', '.join(repr(p) for p in detected)}",
                detected_patterns=detected,
            )

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
        """
        Format a learning/rule as a Graphiti episode.

        Args:
            content: Markdown content (already formatted)
            category: Memory category
            source_file: Original source file (for tracking)
            title: Optional title for naming
            tier: Injection tier for progressive disclosure
            is_golden: Whether this is a golden standard
            is_anti_pattern: Whether this describes an anti-pattern
            confidence: Confidence score (0-100)
            scope: Memory scope (GLOBAL, PROJECT)
            scope_id: Scope identifier (project_id)
            cluster_id: Optional cluster identifier
            validate: Whether to validate content for verbosity (default: True)

        Returns:
            FormattedEpisode ready for Graphiti

        Raises:
            EpisodeValidationError: If validation is enabled and content is too verbose
        """
        # Validate content if requested
        if validate:
            self.validate_content(content)

        # Determine episode name
        if title:
            name = self._slugify(title)
        elif source_file:
            name = f"rule_{source_file.replace('.md', '').replace('-', '_')}"
        else:
            name = f"learning_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        # Build source description with metadata
        source_description = self._build_source_description(
            category=category,
            tier=tier,
            origin=EpisodeOrigin.GOLDEN_STANDARD if is_golden else EpisodeOrigin.RULE_MIGRATION,
            confidence=confidence,
            is_anti_pattern=is_anti_pattern,
            cluster_id=cluster_id,
            source_file=source_file,
        )

        # Determine group_id based on scope
        group_id = self._get_group_id(scope, scope_id)

        return FormattedEpisode(
            name=name,
            episode_body=content,
            source_type=EpisodeType.text,  # Always text for markdown
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
        """
        Format a CLI command cluster as a Graphiti episode.

        CLI commands are stored as OPERATIONAL_CONTEXT with markdown tables.

        Args:
            title: Cluster title (e.g., "st CLI: Active Workflow")
            description: Brief description of the cluster
            commands_markdown: Markdown table of commands
            source_file: Original source file
            cluster_id: Cluster identifier for retrieval

        Returns:
            FormattedEpisode ready for Graphiti
        """
        # Build markdown content
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
        """
        Format an anti-pattern as a Graphiti episode.

        Anti-patterns are stored as GUARDRAIL tier.

        Args:
            title: Anti-pattern title
            content: Markdown content describing the anti-pattern
            source_file: Original source file
            cluster_id: Optional cluster identifier

        Returns:
            FormattedEpisode ready for Graphiti
        """
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
        """
        Format a markdown table row as a declarative fact.

        Converts "| Do | Don't |" style tables into prose for better
        LLM entity extraction.

        Args:
            headers: Table headers
            cells: Cell values for the row
            section_context: Section the table appears in (for context)
            source_file: Original source file
            category: Memory category
            is_golden: Whether this is a golden standard

        Returns:
            FormattedEpisode or None if the row is trivial
        """
        # Build declarative statement
        statement = self._build_declarative_statement(headers, cells, section_context, source_file)

        if not statement or len(statement) < 20:
            return None

        # Determine if anti-pattern based on headers
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
        )

    def chunk_markdown_by_sections(
        self,
        content: str,
        source_file: str,
        category: MemoryCategory,
        *,
        min_chunk_size: int = 50,
        max_chunk_size: int = 2000,
    ) -> list[FormattedEpisode]:
        """
        Split markdown content by H2 headers into separate episodes.

        Per Gemini recommendation: don't store whole files as single episodes.

        Args:
            content: Full markdown content
            source_file: Original source file
            category: Memory category for all chunks
            min_chunk_size: Skip chunks smaller than this
            max_chunk_size: Split chunks larger than this

        Returns:
            List of FormattedEpisodes, one per section
        """
        episodes = []

        # Split by H2 headers
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section or len(section) < min_chunk_size:
                continue

            # Extract title from H2 header
            title_match = re.match(r"^## (.+?)$", section, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else None

            # Check for anti-pattern indicators
            is_anti = bool(
                re.search(r"anti.?pattern|don\'?t|avoid|never|wrong|bad", section, re.IGNORECASE)
            )

            episode = self.format_learning(
                content=section,
                category=category,
                source_file=source_file,
                title=title,
                tier=InjectionTier.GUARDRAIL if is_anti else InjectionTier.REFERENCE,
                is_golden=True,  # Migrated rules are golden
                is_anti_pattern=is_anti,
                confidence=100,
            )
            episodes.append(episode)

        return episodes

    def _build_source_description(
        self,
        category: MemoryCategory,
        tier: InjectionTier,
        origin: EpisodeOrigin,
        confidence: int,
        is_anti_pattern: bool = False,
        cluster_id: str | None = None,
        source_file: str | None = None,
    ) -> str:
        """
        Build source description with metadata for filtering.

        Format: {category} {tier} source:{origin} confidence:{0-100} [type:anti_pattern] [cluster:{id}] [migrated_from:{file}]
        """
        parts = [
            category.value,
            tier.value,
            f"source:{origin.value}",
            f"confidence:{confidence}",
        ]

        if is_anti_pattern:
            parts.append("type:anti_pattern")

        if cluster_id:
            parts.append(f"cluster:{cluster_id}")

        if source_file:
            parts.append(f"migrated_from:{source_file}")

        return " ".join(parts)

    def _build_declarative_statement(
        self,
        headers: list[str],
        cells: list[str],
        section_context: str | None,
        source_file: str | None,
    ) -> str:
        """
        Convert a table row into a declarative prose statement.

        Examples:
            | Do | Don't | -> "Use X instead of Y"
            | Command | Description | -> "The 'X' command does Y"
        """
        if len(headers) < 2 or len(cells) < 2:
            return ""

        h0, h1 = headers[0].lower().strip(), headers[1].lower().strip()
        c0, c1 = cells[0].strip(), cells[1].strip()

        # Do/Don't pattern
        if h0 in ("do", "do instead") and h1 in ("don't", "dont"):
            return f"Use {c0} instead of {c1}."
        if h0 in ("don't", "dont") and h1 in ("do", "do instead"):
            return f"Use {c1} instead of {c0}."

        # Command/Description pattern
        if h0 == "command" and h1 == "description":
            return f"The '{c0}' command {c1.lower() if c1 else 'is available'}."

        # Flag/Action pattern
        if h0 == "flag" and h1 == "action":
            return f"The '{c0}' flag {c1.lower()}."

        # Error/Fix pattern
        if h0 == "error" and h1 == "fix":
            return f"When encountering '{c0}', {c1.lower()}."

        # Generic: just combine with "is related to" or similar
        if c0 and c1:
            # Build context prefix
            ctx = f"{source_file}: " if source_file else ""
            if section_context:
                ctx += f"({section_context}) "

            return f"{ctx}{c0} relates to {c1}."

        return ""

    def _slugify(self, text: str) -> str:
        """Convert text to a slug for episode naming."""
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_]+", "_", slug)
        return slug[:50]  # Limit length

    def _get_group_id(self, scope: MemoryScope, scope_id: str | None) -> str:
        """Determine group_id based on scope using canonical function."""
        return build_group_id(scope, scope_id)


# Singleton instance for convenience
_default_formatter: EpisodeFormatter | None = None


def get_episode_formatter() -> EpisodeFormatter:
    """Get the default EpisodeFormatter instance."""
    global _default_formatter
    if _default_formatter is None:
        _default_formatter = EpisodeFormatter()
    return _default_formatter
