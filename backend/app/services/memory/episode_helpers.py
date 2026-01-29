"""Helper utilities for episode formatting."""

import re
from enum import Enum

from .service import MemoryCategory
from .types import InjectionTier

__all__ = [
    "EpisodeOrigin",
    "InjectionTier",
    "build_declarative_statement",
    "build_source_description",
    "slugify",
]


class EpisodeOrigin(str, Enum):
    """Source origin for episodes."""

    RULE_MIGRATION = "rule_migration"  # Migrated from rules files
    GOLDEN_STANDARD = "golden_standard"  # Curated golden standard
    LEARNING = "learning"  # Runtime learning from sessions
    USER = "user"  # User-provided preference/rule


def build_source_description(
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


def build_declarative_statement(
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


def slugify(text: str) -> str:
    """Convert text to a slug for episode naming."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "_", slug)
    return slug[:50]  # Limit length
