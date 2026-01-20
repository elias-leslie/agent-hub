#!/usr/bin/env python3
"""
Migrate static Claude Code rules to Graphiti knowledge graph.

Per decision d3: Graphiti-first with rules as read-only archive.
Rules are migrated with status='canonical' since they are vetted.

Usage:
    python migrate_rules_to_graphiti.py --dry-run    # Preview without writing
    python migrate_rules_to_graphiti.py              # Run migration
    python migrate_rules_to_graphiti.py --dir /path/to/rules  # Custom rules dir
"""

import argparse
import asyncio
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import memory module components (after path manipulation, so E402 is expected)
from app.services.memory.episode_formatter import (  # noqa: E402
    EpisodeFormatter,
    EpisodeOrigin,
    InjectionTier,
)
from app.services.memory.graphiti_client import get_graphiti  # noqa: E402
from app.services.memory.service import MemoryCategory  # noqa: E402

# Global formatter instance for consistent formatting
_formatter = EpisodeFormatter()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default rules directory
DEFAULT_RULES_DIR = Path.home() / ".claude" / "rules"

# Archive directory per decision d2
ARCHIVE_DIR = Path.home() / ".claude" / "rules.archive"

# Explicit rule categorization from rules-categorization.md
# Maps filename (without .md) to (category, injection_tier, task_filters)
# injection_tier: MANDATE (always), GUARDRAIL (type-filtered), REFERENCE (semantic)
RULE_CATEGORIZATION: dict[str, dict] = {
    # MANDATE tier - always inject
    "anti-patterns": {
        "category": "troubleshooting_guide",
        "tier": "mandate",
        "is_anti_pattern": True,
        "is_golden": True,
    },
    "dev-tools-exclusive": {
        "category": "coding_standard",
        "tier": "mandate",
        "is_golden": True,
    },
    "session-protocol": {
        "category": "operational_context",
        "tier": "mandate",
        "is_golden": True,
    },
    "scope-awareness": {
        "category": "troubleshooting_guide",
        "tier": "mandate",
        "is_anti_pattern": True,
        "is_golden": True,
    },
    "interaction-style": {
        "category": "coding_standard",
        "tier": "mandate",
        "is_golden": True,
    },
    # GUARDRAIL tier - type-filtered
    "db-architecture": {
        "category": "system_design",
        "tier": "guardrail",
        "task_filters": ["database", "migration", "schema"],
        "is_golden": True,
    },
    "browser-testing": {
        "category": "coding_standard",
        "tier": "guardrail",
        "task_filters": ["testing", "ui", "frontend", "browser"],
        "is_golden": True,
    },
    "browser-server": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["browser", "playwright", "ba"],
    },
    "verification": {
        "category": "coding_standard",
        "tier": "guardrail",
        "task_filters": ["testing", "commit", "done"],
        "is_golden": True,
    },
    "quality-gate": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["commit", "testing", "quality"],
    },
    "cloudflare-access": {
        "category": "operational_context",
        "tier": "guardrail",
        "task_filters": ["deploy", "production", "api", "cloudflare"],
    },
    "voice-system": {
        "category": "system_design",
        "tier": "guardrail",
        "task_filters": ["voice", "audio", "whisper"],
    },
    "tech-debt-cleanup": {
        "category": "troubleshooting_guide",
        "tier": "guardrail",
        "task_filters": ["migration", "refactor", "cleanup"],
        "is_anti_pattern": True,
    },
    # REFERENCE tier - semantic retrieval
    "st-cli": {
        "category": "operational_context",
        "tier": "reference",
        "cluster": "cli_tools",
        "is_golden": True,
    },
    "dev-standards": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "development_workflow",
        "is_golden": True,
    },
    "output-format-standard": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "output_formatting",
    },
    "model-standards": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "ai_llm_config",
        "is_golden": True,
    },
    "decision-making": {
        "category": "troubleshooting_guide",
        "tier": "reference",
        "cluster": "decision_process",
    },
    "skill-triggers": {
        "category": "operational_context",
        "tier": "reference",
        "cluster": "skill_system",
    },
    "rule-authoring": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "meta_rules",
    },
    "api-config-pattern": {
        "category": "coding_standard",
        "tier": "reference",
        "cluster": "frontend_patterns",
    },
}


def get_rule_metadata(filename: str) -> dict:
    """Get explicit metadata for a rule file.

    Args:
        filename: Rule filename with .md extension

    Returns:
        Dict with category, tier, is_golden, is_anti_pattern, task_filters, cluster
    """
    stem = Path(filename).stem

    # Use explicit mapping if available
    if stem in RULE_CATEGORIZATION:
        meta = RULE_CATEGORIZATION[stem].copy()
        # Set defaults
        meta.setdefault("is_golden", False)
        meta.setdefault("is_anti_pattern", False)
        meta.setdefault("task_filters", [])
        meta.setdefault("cluster", None)
        return meta

    # Fallback to pattern inference for unknown files
    return {
        "category": _infer_category_fallback(filename),
        "tier": "reference",
        "is_golden": False,
        "is_anti_pattern": False,
        "task_filters": [],
        "cluster": None,
    }


def _infer_category_fallback(filename: str) -> str:
    """Fallback category inference for unmapped files."""
    filename_lower = filename.lower()

    if any(kw in filename_lower for kw in ["anti", "gotcha", "pitfall", "error"]):
        return "troubleshooting_guide"
    if any(kw in filename_lower for kw in ["standard", "style", "pattern"]):
        return "coding_standard"
    if any(kw in filename_lower for kw in ["architecture", "design", "system"]):
        return "system_design"
    if any(kw in filename_lower for kw in ["deploy", "server", "config", "protocol"]):
        return "operational_context"

    return "domain_knowledge"


def parse_markdown_sections(content: str) -> list[dict]:
    """Parse markdown content into sections based on headers."""
    sections = []
    lines = content.split("\n")
    current_section = {"title": "", "content": []}

    for line in lines:
        # Check for header (# or ##)
        header_match = re.match(r"^(#{1,2})\s+(.+)$", line)
        if header_match:
            # Save previous section if it has content
            if current_section["content"]:
                sections.append(current_section)
            current_section = {
                "title": header_match.group(2),
                "level": len(header_match.group(1)),
                "content": [],
            }
        else:
            current_section["content"].append(line)

    # Save last section
    if current_section["content"]:
        sections.append(current_section)

    return sections


def extract_learnings_from_rule(filename: str, content: str) -> list[dict]:
    """Extract individual learnings from a rule file.

    Uses explicit categorization from RULE_CATEGORIZATION.
    For st-cli.md, splits into functional clusters per decision d1.
    For other files, extracts as single learning.
    """
    meta = get_rule_metadata(filename)
    stem = Path(filename).stem

    # Special handling for st-cli.md - split into functional clusters
    if stem == "st-cli":
        return _extract_st_cli_clusters(filename, content, meta)

    # Standard handling for all other files
    return _extract_single_learning(filename, content, meta)


def _extract_single_learning(filename: str, content: str, meta: dict) -> list[dict]:
    """Extract learnings from a rule file.

    Converts markdown tables to structured JSON facts for better semantic search.
    Per Auto-Claude pattern: structured JSON > raw markdown.
    """
    import json

    file_title = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    learnings = []

    # Extract table-based rules as individual facts
    table_facts = _extract_table_facts(content, filename, meta)
    learnings.extend(table_facts)

    # If no table facts found, store the whole file as a summary
    if not table_facts:
        source_description = _build_source_description(meta, filename)

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

    Converts:
        ## Error Handling
        | Don't | Do Instead |
        |-------|------------|
        | X     | Y          |

    To episode body:
        "In the context of Error Handling: Avoid X. Instead, Y."
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
                        source_desc = _build_source_description(meta, filename)

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
    import re

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


def _build_source_description(meta: dict, filename: str) -> str:
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

    # Map string category to MemoryCategory enum
    category_map = {
        "coding_standard": MemoryCategory.CODING_STANDARD,
        "troubleshooting_guide": MemoryCategory.TROUBLESHOOTING_GUIDE,
        "system_design": MemoryCategory.SYSTEM_DESIGN,
        "operational_context": MemoryCategory.OPERATIONAL_CONTEXT,
        "domain_knowledge": MemoryCategory.DOMAIN_KNOWLEDGE,
        "active_state": MemoryCategory.ACTIVE_STATE,
    }
    category = category_map.get(meta["category"], MemoryCategory.CODING_STANDARD)

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


def _extract_st_cli_clusters(filename: str, content: str, meta: dict) -> list[dict]:
    """Extract st-cli.md into functional clusters per decision d1.

    Clusters:
    1. Active Workflow - ready, context, update, close, subtask, step
    2. Planning & Approval - approve, qa, import, verify
    3. Task Management - create, list, show, bug, claim, log
    4. Quality Gate - health, criterion
    5. System Commands - projects, backup, git, sessions, exec
    6. ID Formats & Anti-patterns - ID format rules, errors table
    """
    learnings = []

    # Define clusters with their sections
    clusters = {
        "active_workflow": {
            "title": "st CLI: Active Workflow Commands",
            "description": "Day-to-day task execution commands for SummitFlow CLI",
            "keywords": ["ready", "context", "update", "close", "subtask", "step", "claim", "log"],
            "category": "operational_context",
            "is_golden": True,
        },
        "planning_approval": {
            "title": "st CLI: Planning & Approval",
            "description": "Plan approval and QA workflow commands",
            "keywords": ["approve", "qa", "import", "verify", "Plan Approval"],
            "category": "operational_context",
            "is_golden": True,
        },
        "task_management": {
            "title": "st CLI: Task Management",
            "description": "Creating and managing tasks in SummitFlow",
            "keywords": ["create", "list", "show", "bug", "delete", "cancel"],
            "category": "operational_context",
            "is_golden": True,
        },
        "quality_gate": {
            "title": "st CLI: Quality Gate & Criteria",
            "description": "Health checks and acceptance criteria management",
            "keywords": ["health", "criterion", "Health", "HEALTH"],
            "category": "operational_context",
            "is_golden": True,
        },
        "system_commands": {
            "title": "st CLI: System Commands",
            "description": "Project management, backup, git, and session commands",
            "keywords": ["projects", "backup", "git", "sessions", "exec", "worktree", "autocode"],
            "category": "operational_context",
            "is_golden": False,
        },
    }

    # Extract ID formats and anti-patterns as separate TROUBLESHOOTING_GUIDE entries
    id_format_section = _extract_section(content, "plan.json Schema", "Anti-Patterns")
    if id_format_section:
        learnings.append(
            {
                "content": f"# st CLI: ID Formats (plan.json)\n\n{id_format_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": False,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 cluster:st_cli_id_formats migrated_from:st-cli.md",
            }
        )

    anti_patterns_section = _extract_section(content, "Anti-Patterns", "Errors")
    if anti_patterns_section:
        learnings.append(
            {
                "content": f"# st CLI: Anti-Patterns\n\n{anti_patterns_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": True,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 type:anti_pattern cluster:st_cli_anti_patterns migrated_from:st-cli.md",
            }
        )

    errors_section = _extract_section(content, "Errors", None)
    if errors_section:
        learnings.append(
            {
                "content": f"# st CLI: Common Errors\n\n{errors_section}",
                "category": "troubleshooting_guide",
                "tier": "reference",
                "is_golden": True,
                "is_anti_pattern": False,
                "source_description": "troubleshooting_guide reference source:golden_standard confidence:100 cluster:st_cli_errors migrated_from:st-cli.md",
            }
        )

    # Extract each cluster
    for cluster_id, cluster_meta in clusters.items():
        cluster_content = _extract_cluster_content(content, cluster_meta["keywords"])
        if cluster_content:
            source_desc = (
                f"{cluster_meta['category']} reference "
                f"source:{'golden_standard' if cluster_meta['is_golden'] else 'rule_migration'} "
                f"confidence:{'100' if cluster_meta['is_golden'] else '95'} "
                f"cluster:st_cli_{cluster_id} migrated_from:st-cli.md"
            )

            learnings.append(
                {
                    "content": f"# {cluster_meta['title']}\n\n{cluster_meta['description']}\n\n{cluster_content}",
                    "category": cluster_meta["category"],
                    "tier": "reference",
                    "is_golden": cluster_meta["is_golden"],
                    "is_anti_pattern": False,
                    "source_description": source_desc,
                }
            )

    return learnings


def _extract_section(content: str, start_header: str, end_header: str | None) -> str:
    """Extract content between two headers."""
    lines = content.split("\n")
    in_section = False
    section_lines = []

    for line in lines:
        if f"## {start_header}" in line or f"# {start_header}" in line:
            in_section = True
            section_lines.append(line)
            continue

        if in_section:
            if end_header and (f"## {end_header}" in line or f"# {end_header}" in line):
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _extract_cluster_content(content: str, keywords: list[str]) -> str:
    """Extract lines containing any of the keywords."""
    lines = content.split("\n")
    relevant_lines = []
    in_code_block = False
    include_block = False

    for i, line in enumerate(lines):
        # Track code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                if include_block:
                    relevant_lines.append(line)
                in_code_block = False
                include_block = False
            else:
                in_code_block = True
                # Check if code block content is relevant
                include_block = any(
                    kw.lower() in lines[i + 1].lower() if i + 1 < len(lines) else False
                    for kw in keywords
                )
                if include_block:
                    relevant_lines.append(line)
            continue

        if in_code_block:
            if include_block:
                relevant_lines.append(line)
            continue

        # Check for keyword matches
        if any(kw.lower() in line.lower() for kw in keywords):
            relevant_lines.append(line)
            # Include next few lines for context (tables, etc.)
            for j in range(1, 3):
                if i + j < len(lines) and lines[i + j].strip().startswith("|"):
                    relevant_lines.append(lines[i + j])

    return "\n".join(relevant_lines).strip()


async def migrate_rules(rules_dir: Path, dry_run: bool = False) -> dict:
    """Migrate all rules from directory to Graphiti.

    Args:
        rules_dir: Directory containing .md rule files
        dry_run: If True, preview without writing

    Returns:
        Migration statistics
    """
    stats = {
        "files_processed": 0,
        "learnings_created": 0,
        "golden_standards": 0,
        "anti_patterns": 0,
        "by_tier": {"mandate": 0, "guardrail": 0, "reference": 0},
        "errors": 0,
        "skipped": 0,
    }

    if not rules_dir.exists():
        logger.error("Rules directory not found: %s", rules_dir)
        return stats

    rule_files = list(rules_dir.glob("*.md"))
    logger.info("Found %d rule files in %s", len(rule_files), rules_dir)

    if dry_run:
        logger.info("DRY RUN - no changes will be made")

    graphiti = get_graphiti()

    for rule_file in rule_files:
        try:
            content = rule_file.read_text()
            filename = rule_file.name

            learnings = extract_learnings_from_rule(filename, content)
            logger.info(
                "Extracted %d learnings from %s [%s, golden=%s]",
                len(learnings),
                filename,
                learnings[0]["tier"] if learnings else "?",
                learnings[0]["is_golden"] if learnings else False,
            )

            for learning in learnings:
                if dry_run:
                    logger.info(
                        "  [DRY RUN] Would create: tier=%s, category=%s, golden=%s",
                        learning["tier"],
                        learning["category"],
                        learning["is_golden"],
                    )
                    stats["learnings_created"] += 1
                    stats["by_tier"][learning["tier"]] += 1
                    if learning["is_golden"]:
                        stats["golden_standards"] += 1
                    if learning["is_anti_pattern"]:
                        stats["anti_patterns"] += 1
                    continue

                try:
                    from graphiti_core.nodes import EpisodeType

                    await graphiti.add_episode(
                        name=f"rule_{Path(filename).stem}",
                        episode_body=learning["content"],
                        source=EpisodeType.text,  # Static document
                        source_description=learning["source_description"],
                        reference_time=datetime.now(UTC),
                        group_id="global",  # All rules are GLOBAL scope
                    )

                    stats["learnings_created"] += 1
                    stats["by_tier"][learning["tier"]] += 1
                    if learning["is_golden"]:
                        stats["golden_standards"] += 1
                    if learning["is_anti_pattern"]:
                        stats["anti_patterns"] += 1

                    logger.debug(
                        "Created: %s (%s, tier=%s)",
                        filename,
                        learning["category"],
                        learning["tier"],
                    )

                except Exception as e:
                    logger.error("Failed to create learning: %s", e)
                    stats["errors"] += 1

            stats["files_processed"] += 1

        except Exception as e:
            logger.error("Failed to process %s: %s", rule_file.name, e)
            stats["errors"] += 1

    return stats


def create_archive_readme(archive_dir: Path) -> None:
    """Create a README in the archive directory explaining the migration."""
    readme_content = """# Archived Claude Code Rules

These rules have been migrated to the Graphiti knowledge graph per decision d3.

## What happened?

1. All rules in `~/.claude/rules/` were migrated to Graphiti
2. Rules are now served dynamically from the knowledge graph
3. Original files are preserved here as read-only archive

## Key changes:

- SessionStart hook now injects context from Graphiti instead of static rules
- Learnings from sessions are extracted and stored in Graphiti
- Rules that are referenced frequently get reinforced and promoted

## If you need to add new rules:

1. Use the memory API: `POST /api/memory/add` with appropriate category
2. Or create a learning extraction from session transcripts

## Don't:

- Don't manually edit files in this archive
- Don't copy rules back to ~/.claude/rules/ (they won't be injected)

## See also:

- Agent Hub memory API: http://localhost:8003/docs#/memory
- Migration script: agent-hub/backend/scripts/migrate_rules_to_graphiti.py
"""
    readme_path = archive_dir / "README.md"
    readme_path.write_text(readme_content)
    logger.info("Created archive README at %s", readme_path)


async def archive_rules(rules_dir: Path, archive_dir: Path | None = None) -> None:
    """Move migrated rules to archive directory.

    Per decision d2: Archive to ~/.claude/rules.archive/
    Preserves directory structure for potential rollback.

    Args:
        rules_dir: Original rules directory
        archive_dir: Archive destination (default: ~/.claude/rules.archive/)
    """
    if archive_dir is None:
        archive_dir = ARCHIVE_DIR  # ~/.claude/rules.archive/

    archive_dir.mkdir(parents=True, exist_ok=True)

    rule_files = list(rules_dir.glob("*.md"))
    for rule_file in rule_files:
        dest = archive_dir / rule_file.name
        rule_file.rename(dest)
        logger.info("Archived: %s -> %s", rule_file.name, dest)

    create_archive_readme(archive_dir)
    logger.info("Archived %d rules to %s", len(rule_files), archive_dir)


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate Claude Code rules to Graphiti knowledge graph"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without writing to Graphiti",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_RULES_DIR,
        help=f"Rules directory (default: {DEFAULT_RULES_DIR})",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Move rules to archive after migration (per d3: keep as read-only)",
    )
    args = parser.parse_args()

    logger.info("Starting rule migration")
    logger.info("Rules directory: %s", args.dir)
    logger.info("Dry run: %s", args.dry_run)

    stats = await migrate_rules(args.dir, args.dry_run)

    logger.info("")
    logger.info("Migration complete:")
    logger.info("  Files processed: %d", stats["files_processed"])
    logger.info("  Learnings created: %d", stats["learnings_created"])
    logger.info("  Golden standards: %d", stats["golden_standards"])
    logger.info("  Anti-patterns: %d", stats["anti_patterns"])
    logger.info("  By tier:")
    logger.info("    - mandate: %d", stats["by_tier"]["mandate"])
    logger.info("    - guardrail: %d", stats["by_tier"]["guardrail"])
    logger.info("    - reference: %d", stats["by_tier"]["reference"])
    logger.info("  Errors: %d", stats["errors"])

    # Archive rules if requested and migration was successful
    if args.archive and not args.dry_run and stats["errors"] == 0:
        logger.info("")
        logger.info("Archiving rules...")
        await archive_rules(args.dir)
    elif args.archive and args.dry_run:
        logger.info("")
        logger.info("[DRY RUN] Would archive rules to %s-archive/", args.dir)


if __name__ == "__main__":
    asyncio.run(main())
