"""Batch packing utilities for episode creation."""

from __future__ import annotations

import os

from .episode_creator_models import BatchEpisodeRequest

# Batch packing configuration
# Maximum tokens per batch (Gemini embedding limit is ~8K tokens)
EMBEDDING_BATCH_MAX_TOKENS = int(os.environ.get("EMBEDDING_BATCH_MAX_TOKENS", "8000"))
# Maximum concurrent batches to run simultaneously
EMBEDDING_BATCH_CONCURRENCY = int(os.environ.get("EMBEDDING_BATCH_CONCURRENCY", "4"))


def pack_episodes_into_batches(
    episodes: list[BatchEpisodeRequest],
    max_tokens: int = EMBEDDING_BATCH_MAX_TOKENS,
) -> list[list[BatchEpisodeRequest]]:
    """Pack episodes into token-aware batches.

    Uses first-fit decreasing bin packing algorithm:
    - Sorts episodes by token count (largest first)
    - Places each episode in the first batch that has room
    - Creates new batches as needed

    Episodes exceeding max_tokens are placed in their own batch.

    Args:
        episodes: List of episodes to pack
        max_tokens: Maximum tokens per batch

    Returns:
        List of batches, where each batch is a list of episodes
    """
    if not episodes:
        return []

    # Sort by token count (largest first) for better packing
    sorted_episodes = sorted(episodes, key=lambda e: e.token_count, reverse=True)

    batches: list[list[BatchEpisodeRequest]] = []
    batch_tokens: list[int] = []

    for episode in sorted_episodes:
        tokens = episode.token_count
        placed = False

        # Try to fit in existing batch
        for i, batch in enumerate(batches):
            if batch_tokens[i] + tokens <= max_tokens:
                batch.append(episode)
                batch_tokens[i] += tokens
                placed = True
                break

        # Create new batch if needed
        if not placed:
            batches.append([episode])
            batch_tokens.append(tokens)

    return batches
