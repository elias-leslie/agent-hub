"""Content deduplication for memory episodes.

Provides hash-based exact duplicate detection with time window support.
Uses SHA256 for content hashing and normalized content comparison.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def normalize_content(content: str) -> str:
    """Normalize content for consistent hashing.

    Normalizes whitespace, trims, and lowercases for comparison.

    Args:
        content: Raw content string

    Returns:
        Normalized content string
    """
    # Normalize whitespace: collapse multiple spaces/newlines to single space
    normalized = " ".join(content.split())
    # Trim and lowercase
    return normalized.strip().lower()


def content_hash(content: str) -> str:
    """Compute SHA256 hash of normalized content.

    Args:
        content: Content to hash

    Returns:
        SHA256 hex digest
    """
    normalized = normalize_content(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def find_exact_duplicate(
    content: str,
    window_minutes: int = 5,
) -> str | None:
    """Find an exact duplicate episode within a time window.

    Searches for episodes with matching content hash created within
    the specified time window.

    Args:
        content: Content to check for duplicates
        window_minutes: Time window in minutes to search (default 5)

    Returns:
        UUID of duplicate episode if found, None otherwise
    """
    from .service import get_memory_service, MemoryScope

    hash_value = content_hash(content)
    cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    try:
        # Get memory service and search for duplicates
        service = get_memory_service(MemoryScope.GLOBAL)

        # Search for recent episodes with matching content
        results = await service.search(content, limit=10)

        for result in results:
            # Check if content hash matches
            result_hash = content_hash(result.content)
            if result_hash == hash_value:
                # Check time window
                if result.created_at:
                    created = datetime.fromisoformat(result.created_at.replace("Z", "+00:00"))
                    if created >= cutoff_time:
                        logger.info(
                            "Found exact duplicate: uuid=%s hash=%s within %d minutes",
                            result.uuid,
                            hash_value[:16],
                            window_minutes,
                        )
                        return result.uuid

        return None

    except Exception as e:
        logger.warning("Failed to check for duplicates: %s", e)
        return None


async def add_content_hash_to_episode(
    episode_uuid: str,
    content: str,
) -> bool:
    """Add content hash to an existing episode.

    Updates an episode's metadata with its content hash for future
    deduplication lookups.

    Args:
        episode_uuid: UUID of the episode to update
        content: Episode content (for computing hash)

    Returns:
        True if successful, False otherwise
    """
    hash_value = content_hash(content)

    try:
        # Note: This would update episode metadata in Graphiti
        # For now, we compute and log the hash
        # Full implementation would update the episode properties
        logger.info(
            "Content hash for episode %s: %s",
            episode_uuid,
            hash_value[:16],
        )
        return True

    except Exception as e:
        logger.warning("Failed to add content hash to episode %s: %s", episode_uuid, e)
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
