#!/usr/bin/env python
"""Migrate Neo4j Episodic nodes → PostgreSQL memories table.

Reads all Episodic nodes from Neo4j, generates Gemini embeddings,
and inserts into the unified memories table preserving UUIDs.

Usage:
    # Dry run (default) — shows what would be migrated
    python scripts/memory/migrate_neo4j_to_pg.py

    # Execute migration
    python scripts/memory/migrate_neo4j_to_pg.py --execute

    # Skip embedding generation (faster, embeddings can be added later)
    python scripts/memory/migrate_neo4j_to_pg.py --execute --skip-embeddings
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid as _uuid
from pathlib import Path
from datetime import UTC, datetime

from neo4j import AsyncGraphDatabase
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.db import async_session
from app.models.memory_unified import Memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Neo4j connection (hardcoded — this is a one-time migration script)
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password"

# Tier string → numeric mapping
TIER_MAP = {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}

# Group ID → scope mapping
SCOPE_MAP = {
    "global": "global",
    "project-agent-hub": "project:agent-hub",
    "project-terminal": "project:terminal",
    "project-monkey-fight": "project:monkey-fight",
    "project-summitflow": "project:summitflow",
    "project-portfolio-ai": "project:portfolio-ai",
}

EXPORT_QUERY = """
MATCH (e:Episodic)
RETURN
    e.uuid AS uuid,
    e.name AS name,
    e.content AS content,
    e.summary AS summary,
    e.injection_tier AS injection_tier,
    e.group_id AS group_id,
    e.source AS source,
    e.source_description AS source_description,
    e.pinned AS pinned,
    e.auto_inject AS auto_inject,
    e.display_order AS display_order,
    e.token_count AS token_count,
    e.loaded_count AS loaded_count,
    e.referenced_count AS referenced_count,
    e.helpful_count AS helpful_count,
    e.harmful_count AS harmful_count,
    e.created_at AS created_at,
    e.valid_at AS valid_at,
    e.last_used_at AS last_used_at,
    e.promotion_reason AS promotion_reason,
    e.promoted_at AS promoted_at,
    e.success_count AS success_count,
    e.utility_score AS utility_score,
    e.content_hash AS content_hash,
    e.trigger_task_types AS trigger_task_types,
    e.trigger_phases AS trigger_phases
ORDER BY e.created_at
"""


def neo4j_dt_to_python(val: object) -> datetime | None:
    """Convert Neo4j DateTime to Python datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=UTC) if val.tzinfo is None else val
    # neo4j.time.DateTime
    if hasattr(val, "to_native"):
        native = val.to_native()
        return native.replace(tzinfo=UTC) if native.tzinfo is None else native
    # ISO string fallback
    if isinstance(val, str):
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return None


def map_episode_to_memory(record: dict) -> dict:
    """Map a Neo4j Episodic record to Memory table fields."""
    tier_str = record.get("injection_tier", "reference") or "reference"
    group_id = record.get("group_id", "global") or "global"
    scope = SCOPE_MAP.get(group_id, f"project:{group_id.removeprefix('project-')}")

    # Build metadata for extra fields not in main schema
    metadata = {}
    if record.get("promotion_reason"):
        metadata["promotion_reason"] = record["promotion_reason"]
    if record.get("promoted_at"):
        metadata["promoted_at"] = str(record["promoted_at"])
    if record.get("success_count"):
        metadata["success_count"] = record["success_count"]
    if record.get("content_hash"):
        metadata["content_hash"] = record["content_hash"]

    # Parse trigger arrays — Neo4j may store as list or JSON string
    trigger_task_types = record.get("trigger_task_types")
    if isinstance(trigger_task_types, str):
        try:
            trigger_task_types = json.loads(trigger_task_types)
        except (json.JSONDecodeError, TypeError):
            trigger_task_types = None

    trigger_phases = record.get("trigger_phases")
    if isinstance(trigger_phases, str):
        try:
            trigger_phases = json.loads(trigger_phases)
        except (json.JSONDecodeError, TypeError):
            trigger_phases = None

    return {
        "id": _uuid.UUID(record["uuid"]),
        "content": record["content"],
        "name": record.get("name"),
        "summary": record.get("summary"),
        "memory_type": tier_str,  # mandate/guardrail/reference
        "tier": TIER_MAP.get(tier_str, 3),
        "scope": scope,
        "group_id": group_id,
        "source": record.get("source"),
        "source_description": record.get("source_description"),
        "pinned": bool(record.get("pinned", False)),
        "auto_inject": bool(record.get("auto_inject", False)),
        "display_order": record.get("display_order") or 50,
        "token_count": record.get("token_count"),
        "loaded_count": record.get("loaded_count") or 0,
        "referenced_count": record.get("referenced_count") or 0,
        "helpful_count": record.get("helpful_count") or 0,
        "harmful_count": record.get("harmful_count") or 0,
        "trigger_task_types": trigger_task_types,
        "trigger_phases": trigger_phases,
        "status": "active",
        "metadata_": metadata or {},
        "valid_at": neo4j_dt_to_python(record.get("valid_at")),
        "created_at": neo4j_dt_to_python(record.get("created_at")) or datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "last_accessed_at": neo4j_dt_to_python(record.get("last_used_at")),
    }


async def fetch_episodes() -> list[dict]:
    """Fetch all Episodic nodes from Neo4j."""
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        async with driver.session() as session:
            result = await session.run(EXPORT_QUERY)
            records = [dict(r) async for r in result]
        logger.info("Fetched %d Episodic nodes from Neo4j", len(records))
        return records
    finally:
        await driver.close()


async def _init_credential_manager() -> None:
    """Initialize credential manager so embedder can resolve API keys."""
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    if not cm.is_initialized:
        async with async_session() as session:
            await cm.load(session)
        logger.info("Credential manager initialized with %d providers", len(cm.list_providers()))


async def generate_embeddings(contents: list[str], batch_size: int = 10) -> list[list[float]]:
    """Generate embeddings via Gemini in batches with rate limiting.

    Free tier: 100 requests/minute. Each batch counts as 1 request but
    each item in a batch may count toward the quota.
    """
    await _init_credential_manager()
    from app.services.memory.embedder import get_embedder

    embedder = get_embedder()
    all_embeddings: list[list[float]] = []
    total_batches = (len(contents) + batch_size - 1) // batch_size

    for i in range(0, len(contents), batch_size):
        batch = contents[i : i + batch_size]
        batch_num = i // batch_size + 1
        logger.info("Embedding batch %d/%d (%d items)", batch_num, total_batches, len(batch))

        # Retry with exponential backoff on rate limit
        for attempt in range(5):
            try:
                embeddings = await embedder.embed_batch(batch)
                all_embeddings.extend(embeddings)
                break
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = min(60 * (2 ** attempt), 120)
                    logger.warning("Rate limited at batch %d, waiting %ds (attempt %d/5)",
                                   batch_num, wait, attempt + 1)
                    await asyncio.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError(f"Failed to embed batch {batch_num} after 5 retries")

        # Rate limit: brief pause between batches
        if i + batch_size < len(contents):
            await asyncio.sleep(1)

    return all_embeddings


async def insert_memories(mapped: list[dict], embeddings: list[list[float]] | None) -> int:
    """Insert mapped memories into PostgreSQL."""
    inserted = 0
    async with async_session() as session:
        for i, mem_data in enumerate(mapped):
            if embeddings and i < len(embeddings):
                mem_data["embedding"] = embeddings[i]

            memory = Memory(**mem_data)
            session.add(memory)
            inserted += 1

        await session.commit()
        logger.info("Committed %d memories to PostgreSQL", inserted)

    return inserted


async def verify_migration(expected_count: int) -> bool:
    """Verify migration by comparing counts."""
    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM memories"))
        actual = result.scalar()
        logger.info("Verification: expected=%d, actual=%d", expected_count, actual)

        # Check tier distribution
        result = await session.execute(text(
            "SELECT memory_type, COUNT(*) FROM memories GROUP BY memory_type ORDER BY memory_type"
        ))
        for row in result:
            logger.info("  %s: %d", row[0], row[1])

        # Check scope distribution
        result = await session.execute(text(
            "SELECT scope, COUNT(*) FROM memories GROUP BY scope ORDER BY COUNT(*) DESC"
        ))
        for row in result:
            logger.info("  scope=%s: %d", row[0], row[1])

        return actual == expected_count


async def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Neo4j episodes to PostgreSQL")
    parser.add_argument("--execute", action="store_true", help="Actually execute (default: dry run)")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip embedding generation")
    args = parser.parse_args()

    # Check if memories table already has data
    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM memories"))
        existing = result.scalar()
        if existing > 0:
            logger.error("memories table already has %d rows — aborting to prevent duplicates", existing)
            logger.error("Truncate the table first if you want to re-run: TRUNCATE memories CASCADE")
            sys.exit(1)

    # Fetch from Neo4j
    episodes = await fetch_episodes()
    if not episodes:
        logger.warning("No episodes found in Neo4j")
        return

    # Map to Memory fields
    mapped = [map_episode_to_memory(ep) for ep in episodes]
    logger.info("Mapped %d episodes → memory records", len(mapped))

    # Summary
    tier_counts: dict[str, int] = {}
    scope_counts: dict[str, int] = {}
    for m in mapped:
        tier_counts[m["memory_type"]] = tier_counts.get(m["memory_type"], 0) + 1
        scope_counts[m["scope"]] = scope_counts.get(m["scope"], 0) + 1

    logger.info("Tier distribution: %s", tier_counts)
    logger.info("Scope distribution: %s", scope_counts)
    logger.info("With trigger_task_types: %d", sum(1 for m in mapped if m["trigger_task_types"]))
    logger.info("With pinned=True: %d", sum(1 for m in mapped if m["pinned"]))

    if not args.execute:
        logger.info("DRY RUN — add --execute to perform migration")
        # Print first 3 records as sample
        for m in mapped[:3]:
            logger.info("Sample: id=%s name=%s type=%s scope=%s pinned=%s",
                        str(m["id"])[:8], m["name"], m["memory_type"], m["scope"], m["pinned"])
        return

    # Generate embeddings
    embeddings = None
    if not args.skip_embeddings:
        contents = [m["content"] for m in mapped]
        embeddings = await generate_embeddings(contents)
        logger.info("Generated %d embeddings", len(embeddings))
    else:
        logger.info("Skipping embeddings (--skip-embeddings)")

    # Insert into PostgreSQL
    inserted = await insert_memories(mapped, embeddings)

    # Verify
    ok = await verify_migration(len(episodes))
    if ok:
        logger.info("Migration successful: %d episodes → %d memories", len(episodes), inserted)
    else:
        logger.error("Migration verification FAILED — counts don't match")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
