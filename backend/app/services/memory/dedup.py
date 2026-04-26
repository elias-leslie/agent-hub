"""Content deduplication for memories.

Provides hash-based exact duplicate detection with time window support.
Uses SHA256 for content hashing and normalized content comparison.
Delegates to MemoryRepository.find_duplicate() for database lookup.
"""

import logging

from .fingerprint import content_fingerprint
from .fingerprint import normalize_content as _normalize_content
from .repository import get_memory_repository

logger = logging.getLogger(__name__)


def normalize_content(content: str) -> str:
    """Normalize content for consistent hashing."""
    return _normalize_content(content)


def content_hash(content: str) -> str:
    """Compute SHA256 hash of normalized content.

    Args:
        content: Content to hash

    Returns:
        SHA256 hex digest
    """
    return content_fingerprint(content)


async def find_exact_duplicate(
    content: str,
    window_minutes: int = 5,
    group_id: str | None = None,
) -> str | None:
    """Find an exact duplicate memory within a time window.

    Uses MemoryRepository.find_duplicate() which checks for exact content
    matches created within the specified time window.

    Args:
        content: Content to check for duplicates
        window_minutes: Time window in minutes to search (default 5)
        group_id: Optional group_id filter

    Returns:
        UUID of duplicate memory if found, None otherwise
    """
    try:
        repo = get_memory_repository()
        duplicate_uuid = await repo.find_duplicate(
            content,
            group_id=group_id,
            window_minutes=window_minutes,
        )

        if duplicate_uuid:
            hash_value = content_hash(content)
            logger.info(
                "Found exact duplicate: uuid=%s hash=%s within %d minutes",
                duplicate_uuid[:8],
                hash_value[:16],
                window_minutes,
            )

        return duplicate_uuid

    except Exception as e:
        from .exceptions import DedupError

        logger.warning("Failed to check for duplicates: %s", e)
        if isinstance(e, DedupError):
            raise
        return None


async def add_content_hash_to_episode(
    episode_uuid: str,
    content: str,
) -> bool:
    """Add content hash to an existing memory's metadata.

    Updates a memory's metadata with its content hash for future
    deduplication lookups.

    Args:
        episode_uuid: UUID of the memory to update
        content: Memory content (for computing hash)

    Returns:
        True if successful, False otherwise
    """
    hash_value = content_hash(content)

    try:
        repo = get_memory_repository()
        mem = await repo.get_as_dict(episode_uuid)
        if mem is None:
            logger.warning("Memory %s not found for hash update", episode_uuid[:8])
            return False

        existing_meta = mem.get("metadata", {}) or {}
        existing_meta["content_hash"] = hash_value
        await repo.update(episode_uuid, metadata=existing_meta)

        logger.debug(
            "Content hash for memory %s: %s",
            episode_uuid[:8],
            hash_value[:16],
        )
        return True

    except Exception as e:
        from .exceptions import DedupError

        logger.warning("Failed to add content hash to memory %s: %s", episode_uuid[:8], e)
        if isinstance(e, DedupError):
            raise
        return False


def is_duplicate(content: str, existing_hash: str) -> bool:
    """Check if content matches an existing hash.

    Args:
        content: Content to check
        existing_hash: Previously computed hash

    Returns:
        True if content hash matches existing hash
    """
    return content_hash(content) == existing_hash
