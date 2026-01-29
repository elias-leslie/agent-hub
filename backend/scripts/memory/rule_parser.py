"""Markdown parsing utilities for rule migration.

Converts markdown rule files into structured learnings for Graphiti.
"""

import json
import re
from pathlib import Path

from app.services.memory.episode_formatter import (
    EpisodeFormatter,
    EpisodeOrigin,
    InjectionTier,
)
from app.services.memory.service import MemoryCategory

# Global formatter instance for consistent formatting
_formatter = EpisodeFormatter()


def extract_learnings_from_rule(filename: str, content: str, meta: dict) -> list[dict]:
    """Extract individual learnings from a rule file.

    Uses explicit categorization from RULE_CATEGORIZATION.
    For st-cli.md, splits into functional clusters per decision d1.
    For other files, extracts as single learning.
    """
    stem = Path(filename).stem

    # Special handling for st-cli.md - split into functional clusters
    if stem == "st-cli":
        from .st_cli_splitter import extract_st_cli_clusters

        return extract_st_cli_clusters(filename, content, meta)

    # Standard handling for all other files
    return _extract_single_learning(filename, content, meta)


def _extract_single_learning(filename: str, content: str, meta: dict) -> list[dict]:
    """Extract learnings from a rule file.

    Converts markdown tables to structured JSON facts for better semantic search.
    Per Auto-Claude pattern: structured JSON > raw markdown.
    """
    file_title = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    learnings = []

    # Extract table-based rules as individual facts
    table_facts = _extract_table_facts(content, filename, meta)
    learnings.extend(table_facts)

    # If no table facts found, store the whole file as a summary
    if not table_facts:
        source_description = build_source_description(meta, filename)

        # Convert markdown to clean prose
        clean_content = _markdown_to_prose(content)

        # Create structured JSON content
        episode_data = {
            "type": f"rule_{meta['category']}",
            "title": file_title,
            "tier": meta["tier"],
            "source_file": filename,
            "content": clean_content[:4000],  # Limit for embedding
        }

        if meta.get("task_filters"):
            episode_data["task_filters"] = meta["task_filters"]

        learnings.append(
            {
                "content": json.dumps(episode_data),
                "category": meta["category"],
                "tier": meta["tier"],
                "is_golden": meta["is_golden"],
                "is_anti_pattern": meta["is_anti_pattern"],
                "source_description": source_description,
            }
        )

    return learnings


def _extract_table_facts(content: str, filename: str, meta: dict) -> list[dict]:
    """Extract individual facts from markdown tables.

    Per Gemini Pro recommendation:
    - Each table row becomes a separate episode
    - Episode body is a declarative natural language statement
    - Include section heading as context
    """
    facts = []
    lines = content.split("\n")
    current_section = _get_file_title(filename)  # Default context

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Track section headers for context injection
        if line.startswith("#"):
            header_match = re.match(r"^#{1,3}\s+(.+)$", line)
            if header_match:
                current_section = header_match.group(1).strip()
            i += 1
            continue

        # Detect table header
        if line.startswith("|") and "|" in line[1:]:
            headers = [h.strip() for h in line.split("|")[1:-1]]

            # Skip separator line
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("|--"):
                i += 2
            else:
                i += 1
                continue

            # Process table rows
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                cells = [c.strip() for c in row.split("|")[1:-1]]

                if len(cells) >= 2 and cells[0] and not cells[0].startswith("-"):
                    # Build declarative statement (per Gemini recommendation)
                    episode_body = _build_declarative_statement(
                        headers, cells, current_section, filename
                    )

                    # Skip trivial rows
                    if episode_body and len(episode_body) > 20:
                        source_desc = build_source_description(meta, filename)

                        # Determine if this is an anti-pattern
                        header_lower = [h.lower() for h in headers]
                        is_anti = any(
                            kw in header_lower for kw in ["don't", "dont", "never", "avoid"]
                        )

                        facts.append(
                            {
                                "content": episode_body,
                                "category": meta["category"],
                                "tier": meta["tier"],
                                "is_golden": meta["is_golden"],
                                "is_anti_pattern": is_anti or meta.get("is_anti_pattern", False),
                                "source_description": source_desc,
                            }
                        )

                i += 1
        else:
            i += 1

    return facts


def _get_file_title(filename: str) -> str:
    """Convert filename to readable title."""
    return Path(filename).stem.replace("-", " ").replace("_", " ").title()


def _build_declarative_statement(
    headers: list[str],
    cells: list[str],
    section: str,
    filename: str,
) -> str:
    """Build a natural language declarative statement from table row.

    Per Gemini Pro: "In the context of {Heading}, avoid {Cell 1}. Instead, {Cell 2}."
    """
    if len(cells) < 2:
        return ""

    header_lower = [h.lower() for h in headers]
    col1, col2 = cells[0], cells[1]

    # Skip empty or header-like content
    if not col1 or not col2 or col1.startswith("-"):
        return ""

    # Pattern: Don't | Do Instead
    if any(kw in header_lower for kw in ["don't", "dont", "never"]):
        return f"In {section}: Avoid {col1}. Instead, {col2}."

    # Pattern: Do | Don't
    if (
        any(kw in header_lower for kw in ["do"])
        and len(headers) > 1
        and any(kw in headers[1].lower() for kw in ["don't", "dont"])
    ):
        return f"In {section}: {col1} is correct. Avoid {col2}."

    # Pattern: Trigger | Action (skill triggers, etc.)
    if any(kw in header_lower for kw in ["trigger", "phrase", "when"]):
        return f"In {section}: When you see '{col1}', {col2}."

    # Pattern: Command | Description (CLI docs)
    if any(kw in header_lower for kw in ["command", "subcommand", "flag"]):
        return f"In {section}: The command {col1} - {col2}."

    # Pattern: Check | Requirement (checklists)
    if any(kw in header_lower for kw in ["check", "requirement", "rule"]):
        return f"In {section}: {col1} requires {col2}."

    # Pattern: Status | Meaning
    if any(kw in header_lower for kw in ["status", "code", "level"]):
        return f"In {section}: {col1} means {col2}."

    # Pattern: Element | Pattern/Style
    if any(kw in header_lower for kw in ["element", "component", "type"]):
        return f"In {section}: For {col1}, use {col2}."

    # Generic fallback: Header1: Cell1 | Header2: Cell2
    parts = []
    for idx, header in enumerate(headers):
        if idx < len(cells) and cells[idx]:
            parts.append(f"{header}: {cells[idx]}")

    if parts:
        return f"In {section}: {' | '.join(parts)}."

    return ""


def _markdown_to_prose(content: str) -> str:
    """Convert markdown to clean prose for embedding.

    Removes formatting characters while preserving meaning.
    """
    # Remove markdown headers
    content = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)

    # Convert **bold** and *italic* to plain text
    content = re.sub(r"\*\*([^*]+)\*\*", r"\1", content)
    content = re.sub(r"\*([^*]+)\*", r"\1", content)

    # Convert `code` to plain text
    content = re.sub(r"`([^`]+)`", r"\1", content)

    # Remove code blocks (keep content)
    content = re.sub(r"```[\w]*\n", "", content)
    content = re.sub(r"```", "", content)

    # Convert list markers to prose
    content = re.sub(r"^[-*+]\s+", "• ", content, flags=re.MULTILINE)
    content = re.sub(r"^\d+\.\s+", "", content, flags=re.MULTILINE)

    # Clean up extra whitespace
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def build_source_description(meta: dict, filename: str) -> str:
    """Build structured source_description using EpisodeFormatter (DRY).

    Delegates to the shared EpisodeFormatter for consistent source descriptions
    across all episode creation paths.
    """
    # Map string tier to InjectionTier enum
    tier_map = {
        "mandate": InjectionTier.MANDATE,
        "guardrail": InjectionTier.GUARDRAIL,
        "reference": InjectionTier.REFERENCE,
    }
    tier = tier_map.get(meta["tier"], InjectionTier.REFERENCE)

    # Map string category to tier-first MemoryCategory enum
    # troubleshooting_guide -> GUARDRAIL, everything else -> REFERENCE (mandates have is_golden=True)
    if meta.get("is_golden"):
        category = MemoryCategory.MANDATE
    elif meta["category"] == "troubleshooting_guide":
        category = MemoryCategory.GUARDRAIL
    else:
        category = MemoryCategory.REFERENCE

    # Determine origin based on is_golden
    origin = EpisodeOrigin.GOLDEN_STANDARD if meta["is_golden"] else EpisodeOrigin.RULE_MIGRATION

    # Build source description using formatter
    return _formatter._build_source_description(
        category=category,
        tier=tier,
        origin=origin,
        confidence=100 if meta["is_golden"] else 95,
        is_anti_pattern=meta.get("is_anti_pattern", False),
        cluster_id=meta.get("cluster"),
        source_file=filename,
    )
