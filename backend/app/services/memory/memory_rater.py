"""Loaded-memory selection for the summary workflow's combined helpfulness rating.

The summary workflow rates loaded memories inside its own LLM call; this module only
bounds and fetches the memories it rates.
"""

from __future__ import annotations

# Only rate sessions with enough loaded memories to be meaningful
MIN_MEMORIES_TO_RATE = 3

# Cap memories sent to LLM to control token cost
MAX_MEMORIES_TO_RATE = 30


async def _fetch_memory_contents(uuids: list[str]) -> dict[str, str]:
    """Fetch memory content from PostgreSQL via MemoryRepository.

    Returns:
        Dict mapping UUID to content string
    """
    from .repository import get_memory_repository

    repo = get_memory_repository()
    batch = await repo.batch_get(uuids)
    return {uuid: data["content"] for uuid, data in batch.items() if data.get("content")}
