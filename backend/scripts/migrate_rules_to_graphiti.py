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
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Import after path manipulation (E402 expected)
from app.services.memory.graphiti_client import get_graphiti  # noqa: E402
from scripts.memory.rule_categorization import get_rule_metadata  # noqa: E402
from scripts.memory.rule_parser import extract_learnings_from_rule  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default rules directory
DEFAULT_RULES_DIR = Path.home() / ".claude" / "rules"

# Archive directory per decision d2
ARCHIVE_DIR = Path.home() / ".claude" / "rules.archive"


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

            # Get metadata and extract learnings
            meta = get_rule_metadata(filename)
            learnings = extract_learnings_from_rule(filename, content, meta)

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
                    _update_stats(stats, learning)
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

                    _update_stats(stats, learning)

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


def _update_stats(stats: dict, learning: dict) -> None:
    """Update statistics with learning metadata."""
    stats["learnings_created"] += 1
    stats["by_tier"][learning["tier"]] += 1
    if learning["is_golden"]:
        stats["golden_standards"] += 1
    if learning["is_anti_pattern"]:
        stats["anti_patterns"] += 1


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
