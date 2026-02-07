#!/usr/bin/env python3
"""Backfill episode tags based on content keyword analysis.

Scans all episodes in Neo4j, matches content against keyword→tag mappings,
and sets tags via episode_property_setters. Idempotent: merges with existing tags.

Usage:
    cd backend && .venv/bin/python scripts/backfill_episode_tags.py [--dry-run] [--group-id global]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TAG_KEYWORDS: dict[str, list[str]] = {
    "frontend": [
        "frontend", "react", "next.js", "nextjs", "css", "dark mode", "dark-mode",
        "component", "ui", "tailwind", "tsx", "jsx", "sidebar", "navigation",
        "pwa", "service worker", "manifest",
    ],
    "backend": [
        "backend", "fastapi", "sqlalchemy", "celery", "endpoint", "uvicorn",
        "alembic", "migration", "api endpoint", "rest api",
    ],
    "browser": [
        "browser", "puppeteer", "screenshot", "click", "navigate", "page load",
        "playwright", "selenium",
    ],
    "testing": [
        "test", "pytest", "fixture", "mock", "assert", "coverage", "test_",
    ],
    "git": [
        "git commit", "git branch", "worktree", "git merge", "rebase",
        "git push", "git pull", "git reset", "git restore",
    ],
    "python": [
        "python", "async", "type hint", "decorator", "asyncio", "pydantic",
    ],
    "typescript": [
        "typescript", "interface", "tsx", "next.js", "nextjs", "biome",
    ],
    "database": [
        "database", "migration", "schema", "table", "column", "sql",
        "postgresql", "neo4j", "graphiti", "alembic",
    ],
    "infra": [
        "deploy", "systemd", "nginx", "service", "restart", "systemctl",
    ],
    "networking": [
        "cors", "cf access", "cloudflare", "proxy", "websocket",
    ],
    "memory": [
        "memory", "mandate", "guardrail", "episode", "injection", "graphiti",
        "progressive context",
    ],
}

WORD_BOUNDARY_TAGS = {"git", "testing"}


def match_tags(content: str) -> set[str]:
    """Match content against keyword→tag mappings."""
    content_lower = content.lower()
    matched: set[str] = set()

    for tag, keywords in TAG_KEYWORDS.items():
        for kw in keywords:
            if tag in WORD_BOUNDARY_TAGS:
                if re.search(rf"\b{re.escape(kw)}\b", content_lower):
                    matched.add(tag)
                    break
            else:
                if kw in content_lower:
                    matched.add(tag)
                    break

    return matched


async def backfill(group_id: str = "global", dry_run: bool = False) -> None:
    from app.services.memory.neo4j_queries import execute_episode_query
    from app.services.memory.episode_property_setters import set_episode_tags

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN e.uuid AS uuid,
           e.content AS content,
           COALESCE(e.tags, []) AS existing_tags
    ORDER BY e.created_at ASC
    """

    records = await execute_episode_query(
        query, {"group_id": group_id}, None, "backfill fetch"
    )

    logger.info("Fetched %d episodes from group '%s'", len(records), group_id)

    tagged_count = 0
    skipped_count = 0
    all_tags: set[str] = set()

    for record in records:
        uuid = record["uuid"]
        content = record["content"] or ""
        existing = set(record["existing_tags"])

        new_tags = match_tags(content)
        merged = sorted(existing | new_tags)
        all_tags.update(merged)

        if set(merged) == existing:
            skipped_count += 1
            continue

        if dry_run:
            logger.info("[DRY RUN] %s: %s → %s", uuid[:8], sorted(existing), merged)
        else:
            await set_episode_tags(uuid, merged)
            logger.info("Tagged %s: %s", uuid[:8], merged)

        tagged_count += 1

    logger.info(
        "Done: tagged=%d, skipped=%d, unique_tags=%d (%s)",
        tagged_count,
        skipped_count,
        len(all_tags),
        sorted(all_tags),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill episode tags from content keywords")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--group-id", default="global", help="Neo4j group_id (default: global)")
    args = parser.parse_args()

    asyncio.run(backfill(group_id=args.group_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
