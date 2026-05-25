"""Memory episode storage for completion conversations."""

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.completion.auto_thinking import extract_text_content
from app.services.completion.types import CompletionSource
from app.services.memory.episode_creator import get_episode_creator
from app.services.memory.ingestion_config import CHAT_STREAM
from app.services.memory.service import MemorySource

logger = logging.getLogger(__name__)


async def store_episode(
    messages: list[dict[str, Any]],
    response: str,
    source: str,
    group_id: str,
) -> str | None:
    """
    Store conversation as a memory episode.

    Args:
        messages: The conversation messages.
        response: The assistant's response.
        source: Source of the conversation (chat, voice, stream).
        group_id: Memory group ID for isolation.

    Returns:
        UUID of the created episode, or None if storage failed.
    """
    try:
        # Get the last user message for episode content
        last_user_msg = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        user_text = extract_text_content(last_user_msg)

        # Build episode content (user input + assistant response)
        episode_content = f"User: {user_text}\nAssistant: {response}"

        # Map source to memory source
        memory_source = (
            MemorySource.VOICE if source == CompletionSource.VOICE else MemorySource.CHAT
        )

        # Store episode
        creator = get_episode_creator(scope_id=group_id)
        result = await creator.create(
            content=episode_content,
            name=f"{source}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
            config=CHAT_STREAM,
            source_description=f"{source} conversation",
            reference_time=datetime.now(UTC),
            source=memory_source,
        )

        if result.success:
            logger.info(f"Stored {source} conversation as episode {result.uuid}")
            return result.uuid
        return None

    except Exception as e:
        logger.warning(f"Failed to store episode: {e}")
        return None


async def store_episode_background(
    messages: list[dict[str, Any]],
    response: str,
    source: str,
    group_id: str,
) -> None:
    """
    Background wrapper for episode storage with error handling.

    Used for fire-and-forget storage (e.g., voice) where we don't want to
    block the response. Errors are logged but don't propagate.
    """
    try:
        await store_episode(
            messages=messages,
            response=response,
            source=source,
            group_id=group_id,
        )
    except Exception as e:
        # Log but don't raise - this is fire-and-forget
        logger.error(f"Background episode storage failed: {e}")
