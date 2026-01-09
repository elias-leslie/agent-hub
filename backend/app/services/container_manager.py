"""Container management for code execution environments.

Manages container lifecycle for programmatic tool calling, tracking
container IDs, expiration times, and reuse across requests.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Default container expiration (~4.5 minutes per API docs)
DEFAULT_EXPIRATION_MINUTES = 4.5


@dataclass
class Container:
    """A code execution container."""

    id: str
    expires_at: datetime
    session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if container has expired."""
        return datetime.now(UTC) >= self.expires_at

    @property
    def time_remaining(self) -> timedelta:
        """Get time remaining before expiration."""
        remaining = self.expires_at - datetime.now(UTC)
        return max(remaining, timedelta(0))


class ContainerManager:
    """
    Manages code execution containers for programmatic tool calling.

    Containers are created by Claude's API and expire after ~4.5 minutes
    of inactivity. This manager tracks container IDs for reuse within
    sessions.
    """

    def __init__(self) -> None:
        """Initialize container manager."""
        # Map session_id -> Container
        self._session_containers: dict[str, Container] = {}
        # Map container_id -> Container
        self._containers: dict[str, Container] = {}

    def register(
        self,
        container_id: str,
        expires_at: datetime | str,
        session_id: str | None = None,
    ) -> Container:
        """
        Register a container from an API response.

        Args:
            container_id: Container ID from API
            expires_at: Expiration timestamp (datetime or ISO string)
            session_id: Optional session to associate container with

        Returns:
            Registered Container object
        """
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

        container = Container(
            id=container_id,
            expires_at=expires_at,
            session_id=session_id,
        )

        self._containers[container_id] = container
        if session_id:
            self._session_containers[session_id] = container

        logger.info(
            f"Registered container {container_id} for session {session_id}, "
            f"expires in {container.time_remaining}"
        )

        return container

    def get_for_session(self, session_id: str) -> Container | None:
        """
        Get a valid container for a session, if one exists.

        Args:
            session_id: Session ID to look up

        Returns:
            Active container or None if no valid container exists
        """
        container = self._session_containers.get(session_id)
        if container and not container.is_expired:
            return container

        # Clean up expired container
        if container:
            self._cleanup_container(container)

        return None

    def get(self, container_id: str) -> Container | None:
        """
        Get a container by ID.

        Args:
            container_id: Container ID to look up

        Returns:
            Container or None if not found or expired
        """
        container = self._containers.get(container_id)
        if container and not container.is_expired:
            return container

        # Clean up expired container
        if container:
            self._cleanup_container(container)

        return None

    def update_expiration(
        self, container_id: str, expires_at: datetime | str
    ) -> Container | None:
        """
        Update container expiration time (from API response).

        Args:
            container_id: Container ID to update
            expires_at: New expiration timestamp

        Returns:
            Updated container or None if not found
        """
        container = self._containers.get(container_id)
        if not container:
            return None

        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

        container.expires_at = expires_at
        logger.debug(
            f"Updated container {container_id} expiration, "
            f"now expires in {container.time_remaining}"
        )
        return container

    def invalidate(self, container_id: str) -> None:
        """
        Invalidate a container (e.g., after error or explicit expiration).

        Args:
            container_id: Container ID to invalidate
        """
        container = self._containers.get(container_id)
        if container:
            self._cleanup_container(container)
            logger.info(f"Invalidated container {container_id}")

    def cleanup_expired(self) -> int:
        """
        Remove all expired containers.

        Returns:
            Number of containers cleaned up
        """
        expired = [c for c in self._containers.values() if c.is_expired]
        for container in expired:
            self._cleanup_container(container)

        if expired:
            logger.info(f"Cleaned up {len(expired)} expired containers")

        return len(expired)

    def _cleanup_container(self, container: Container) -> None:
        """Remove container from all tracking dicts."""
        self._containers.pop(container.id, None)
        if container.session_id:
            self._session_containers.pop(container.session_id, None)


# Global container manager instance
_container_manager: ContainerManager | None = None


def get_container_manager() -> ContainerManager:
    """Get the global container manager instance."""
    global _container_manager
    if _container_manager is None:
        _container_manager = ContainerManager()
    return _container_manager


def clear_container_manager() -> None:
    """Clear the global container manager (for testing)."""
    global _container_manager
    _container_manager = None
