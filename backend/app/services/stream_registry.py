"""
Stream registry service for tracking and cancelling active streams.

Uses Redis to track active streaming sessions across instances,
enabling REST-based cancellation of WebSocket streams.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key prefix for active streams
STREAM_PREFIX = "agent-hub:stream:"
# TTL for stream registry entries (5 minutes - streams shouldn't last longer)
STREAM_TTL = 300


@dataclass
class StreamState:
    """State of an active stream."""

    session_id: str
    model: str
    started_at: str
    input_tokens: int = 0
    output_tokens: int = 0
    cancelled: bool = False
    cancelled_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StreamState":
        """Create from dictionary."""
        return cls(**data)


class StreamRegistry:
    """Redis-based registry for tracking active streams."""

    def __init__(self, redis_url: str | None = None):
        """
        Initialize stream registry.

        Args:
            redis_url: Redis connection URL. Falls back to settings.
        """
        self._redis_url = redis_url or settings.agent_hub_redis_url
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    def _key(self, session_id: str) -> str:
        """Generate Redis key for a session."""
        return f"{STREAM_PREFIX}{session_id}"

    async def register_stream(
        self,
        session_id: str,
        model: str,
        input_tokens: int = 0,
    ) -> StreamState:
        """
        Register a new active stream.

        Args:
            session_id: Session ID for the stream
            model: Model being used
            input_tokens: Initial input token count

        Returns:
            StreamState for the registered stream
        """
        try:
            client = await self._get_client()
            state = StreamState(
                session_id=session_id,
                model=model,
                started_at=datetime.utcnow().isoformat(),
                input_tokens=input_tokens,
                output_tokens=0,
                cancelled=False,
                cancelled_at=None,
            )
            await client.setex(
                self._key(session_id),
                STREAM_TTL,
                json.dumps(state.to_dict()),
            )
            logger.info(f"Registered stream for session {session_id}")
            return state
        except Exception as e:
            logger.warning(f"Failed to register stream: {e}")
            # Return state anyway so streaming can continue
            return StreamState(
                session_id=session_id,
                model=model,
                started_at=datetime.utcnow().isoformat(),
            )

    async def get_stream(self, session_id: str) -> StreamState | None:
        """
        Get state of an active stream.

        Args:
            session_id: Session ID to look up

        Returns:
            StreamState if found, None otherwise
        """
        try:
            client = await self._get_client()
            data = await client.get(self._key(session_id))
            if data:
                return StreamState.from_dict(json.loads(data))
            return None
        except Exception as e:
            logger.warning(f"Failed to get stream state: {e}")
            return None

    async def update_tokens(
        self,
        session_id: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> StreamState | None:
        """
        Update token counts for an active stream.

        Args:
            session_id: Session ID to update
            input_tokens: New input token count (if provided)
            output_tokens: New output token count (if provided)

        Returns:
            Updated StreamState or None if not found
        """
        try:
            client = await self._get_client()
            key = self._key(session_id)
            data = await client.get(key)
            if not data:
                return None

            state = StreamState.from_dict(json.loads(data))
            if input_tokens is not None:
                state.input_tokens = input_tokens
            if output_tokens is not None:
                state.output_tokens = output_tokens

            # Refresh TTL when updating
            await client.setex(key, STREAM_TTL, json.dumps(state.to_dict()))
            return state
        except Exception as e:
            logger.warning(f"Failed to update tokens: {e}")
            return None

    async def cancel_stream(self, session_id: str) -> StreamState | None:
        """
        Cancel an active stream.

        Sets the cancelled flag which the streaming handler will check.

        Args:
            session_id: Session ID to cancel

        Returns:
            Updated StreamState with cancellation info, or None if not found
        """
        try:
            client = await self._get_client()
            key = self._key(session_id)
            data = await client.get(key)
            if not data:
                logger.warning(f"No active stream for session {session_id}")
                return None

            state = StreamState.from_dict(json.loads(data))
            if state.cancelled:
                # Already cancelled
                return state

            state.cancelled = True
            state.cancelled_at = datetime.utcnow().isoformat()

            # Keep in registry briefly so streaming handler can read cancellation
            await client.setex(key, STREAM_TTL, json.dumps(state.to_dict()))
            logger.info(f"Cancelled stream for session {session_id}")
            return state
        except Exception as e:
            logger.warning(f"Failed to cancel stream: {e}")
            return None

    async def is_cancelled(self, session_id: str) -> bool:
        """
        Check if a stream has been cancelled.

        Args:
            session_id: Session ID to check

        Returns:
            True if cancelled, False otherwise
        """
        state = await self.get_stream(session_id)
        return state is not None and state.cancelled

    async def unregister_stream(self, session_id: str) -> bool:
        """
        Remove a stream from the registry.

        Called when streaming completes or is cancelled.

        Args:
            session_id: Session ID to remove

        Returns:
            True if removed, False if not found
        """
        try:
            client = await self._get_client()
            result = await client.delete(self._key(session_id))
            if result > 0:
                logger.info(f"Unregistered stream for session {session_id}")
            return result > 0
        except Exception as e:
            logger.warning(f"Failed to unregister stream: {e}")
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Singleton instance
_stream_registry: StreamRegistry | None = None


def get_stream_registry() -> StreamRegistry:
    """Get the singleton stream registry instance."""
    global _stream_registry
    if _stream_registry is None:
        _stream_registry = StreamRegistry()
    return _stream_registry
