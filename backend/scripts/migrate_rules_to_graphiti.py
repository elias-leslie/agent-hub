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
from datetime import datetime
from pathlib import Path

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import only what we need - avoid triggering full memory module import
from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default rules directory
DEFAULT_RULES_DIR = Path.home() / ".claude" / "rules"

# Category inference patterns
CATEGORY_PATTERNS = {
    "coding_standard": [
        r"standard",
        r"style",
        r"convention",
        r"pattern",
        r"best.?practice",
        r"format",
    ],
    "troubleshooting_guide": [
        r"anti.?pattern",
        r"gotcha",
        r"pitfall",
        r"fix",
        r"error",
        r"issue",
        r"don't",
        r"never",
        r"avoid",
    ],
    "system_design": [
        r"architecture",
        r"design",
        r"structure",
        r"cli",
        r"api",
        r"endpoint",
        r"system",
    ],
    "operational_context": [
        r"deploy",
        r"server",
        r"environment",
        r"config",
        r"setup",
        r"service",
        r"protocol",
    ],
    "domain_knowledge": [
        r"domain",
        r"business",
        r"rule",
        r"workflow",
        r"trigger",
        r"decision",
    ],
}


def infer_category(filename: str, content: str) -> str:
    """Infer memory category from filename and content."""
    combined = f"{filename} {content[:500]}".lower()

    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined):
                return category

    return "domain_knowledge"  # Default


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

    Each rule file may contain multiple distinct learnings.
    Tables become individual learnings for each row.
    """
    learnings = []

    # Parse into sections
    sections = parse_markdown_sections(content)

    # Add the file-level title as a learning
    file_title = Path(filename).stem.replace("-", " ").replace("_", " ").title()
    learnings.append({
        "content": f"Rule: {file_title}. {content[:500]}...",
        "category": infer_category(filename, content),
    })

    # Extract table-based learnings (common in rules)
    table_rows = re.findall(r"\|([^|]+)\|([^|]+)\|", content)
    for row in table_rows:
        col1, col2 = row[0].strip(), row[1].strip()
        # Skip header rows
        if col1.startswith("-") or col2.startswith("-"):
            continue
        if not col1 or not col2:
            continue
        # Create learning from table row
        learning_content = f"{col1}: {col2}"
        if len(learning_content) > 20:  # Skip trivial rows
            learnings.append({
                "content": learning_content,
                "category": infer_category(filename, learning_content),
            })

    return learnings


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
            logger.info("Extracted %d learnings from %s", len(learnings), filename)

            for learning in learnings:
                if dry_run:
                    logger.info(
                        "  [DRY RUN] Would create: %s (%s)",
                        learning["content"][:60],
                        learning["category"],
                    )
                    stats["learnings_created"] += 1
                    continue

                try:
                    # Create episode in Graphiti
                    source_description = (
                        f"{learning['category']} canonical "
                        f"migrated_from_rule:{filename} "
                        f"confidence:95 status:canonical"
                    )

                    await graphiti.add_episode(
                        name=f"rule_migration_{filename}_{datetime.now().isoformat()}",
                        episode_body=learning["content"],
                        source="system",  # EpisodeType
                        source_description=source_description,
                        reference_time=datetime.now(),
                        group_id="global",  # Per d4: shared global scope
                    )

                    stats["learnings_created"] += 1
                    logger.debug("Created learning: %s", learning["content"][:60])

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

    Args:
        rules_dir: Original rules directory
        archive_dir: Archive destination (default: ~/.claude/rules-archive/)
    """
    if archive_dir is None:
        archive_dir = rules_dir.parent / "rules-archive"

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
    logger.info("  Errors: %d", stats["errors"])
    logger.info("  Skipped: %d", stats["skipped"])

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
