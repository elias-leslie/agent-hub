"""
GraphitiState tracking for memory system.

Tracks session-level state for Graphiti memory operations including:
- session_id from Claude Code hooks
- active memory scope and scope_id
- context injection metrics
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .service import MemoryScope

# Persistence location
STATE_FILE = Path.home() / ".agent-hub" / ".graphiti_state.json"

logger = logging.getLogger(__name__)


@dataclass
class GraphitiState:
    """
    Session-level state for Graphiti memory operations.

    Tracks session context, active scope, and injection metrics for
    memory operations within a single Claude Code session or API interaction.

    Attributes:
        session_id: Session identifier from Claude Code hooks or API
        scope: Active memory scope (GLOBAL or PROJECT)
        scope_id: Identifier for the active scope (project_id or None)
        created_at: When this state was initialized
        last_injection_at: Timestamp of last context injection
        injection_count: Number of context injections in this session
        loaded_memory_uuids: UUIDs of memories loaded in this session (for tracking)
        metadata: Additional session metadata (e.g., user_id, task_id)
    """

    session_id: str
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_injection_at: datetime | None = None
    injection_count: int = 0
    loaded_memory_uuids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_injection(self, memory_uuids: list[str]) -> None:
        """
        Record a context injection event.

        Args:
            memory_uuids: List of memory UUIDs that were injected
        """
        self.last_injection_at = datetime.now(UTC)
        self.injection_count += 1

        # Add new UUIDs to loaded list (avoiding duplicates)
        for uuid in memory_uuids:
            if uuid not in self.loaded_memory_uuids:
                self.loaded_memory_uuids.append(uuid)

        logger.debug(
            "Recorded injection: session=%s count=%d memories=%d",
            self.session_id,
            self.injection_count,
            len(memory_uuids),
        )

    def set_scope(self, scope: MemoryScope, scope_id: str | None = None) -> None:
        """
        Update the active memory scope.

        Args:
            scope: New memory scope (GLOBAL or PROJECT)
            scope_id: Identifier for the scope (project_id or None for GLOBAL)
        """
        self.scope = scope
        self.scope_id = scope_id
        logger.debug(
            "Updated scope: session=%s scope=%s scope_id=%s",
            self.session_id,
            scope.value,
            scope_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert state to dict for serialization.

        Returns:
            Dict representation of state
        """
        return {
            "session_id": self.session_id,
            "scope": self.scope.value,
            "scope_id": self.scope_id,
            "created_at": self.created_at.isoformat(),
            "last_injection_at": self.last_injection_at.isoformat()
            if self.last_injection_at
            else None,
            "injection_count": self.injection_count,
            "loaded_memory_count": len(self.loaded_memory_uuids),
            "loaded_memory_uuids": self.loaded_memory_uuids,
            "metadata": self.metadata,
        }

    def save(self) -> None:
        """
        Persist state to disk at ~/.agent-hub/.graphiti_state.json.

        Creates the ~/.agent-hub directory if it doesn't exist.
        """
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with STATE_FILE.open("w") as f:
            json.dump(self.to_dict(), f, indent=2)
        logger.debug("Saved state to %s", STATE_FILE)

    @classmethod
    def load(cls, session_id: str | None = None) -> "GraphitiState | None":
        """
        Load state from disk.

        Args:
            session_id: If provided, only return state if session_id matches

        Returns:
            GraphitiState if file exists (and session_id matches), None otherwise
        """
        if not STATE_FILE.exists():
            return None

        try:
            with STATE_FILE.open() as f:
                data = json.load(f)

            # Check session_id if provided
            if session_id and data.get("session_id") != session_id:
                return None

            # Parse datetime fields
            created_at = datetime.fromisoformat(data["created_at"])
            last_injection_at = (
                datetime.fromisoformat(data["last_injection_at"])
                if data.get("last_injection_at")
                else None
            )

            return cls(
                session_id=data["session_id"],
                scope=MemoryScope(data.get("scope", "global")),
                scope_id=data.get("scope_id"),
                created_at=created_at,
                last_injection_at=last_injection_at,
                injection_count=data.get("injection_count", 0),
                loaded_memory_uuids=data.get("loaded_memory_uuids", []),
                metadata=data.get("metadata", {}),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to load state from %s: %s", STATE_FILE, e)
            return None


# Session state registry (in-memory for now, could be Redis for multi-process)
_state_registry: dict[str, GraphitiState] = {}


def get_state(session_id: str) -> GraphitiState | None:
    """
    Get GraphitiState for a session.

    Args:
        session_id: Session identifier

    Returns:
        GraphitiState if exists, None otherwise
    """
    return _state_registry.get(session_id)


def create_state(
    session_id: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> GraphitiState:
    """
    Create a new GraphitiState for a session.

    If state already exists for the session, returns the existing state.

    Args:
        session_id: Session identifier
        scope: Initial memory scope
        scope_id: Initial scope identifier
        metadata: Additional session metadata

    Returns:
        GraphitiState for the session
    """
    if session_id in _state_registry:
        logger.debug("Session state already exists: %s", session_id)
        return _state_registry[session_id]

    state = GraphitiState(
        session_id=session_id,
        scope=scope,
        scope_id=scope_id,
        metadata=metadata or {},
    )
    _state_registry[session_id] = state
    logger.info("Created session state: %s scope=%s", session_id, scope.value)
    return state


def delete_state(session_id: str) -> bool:
    """
    Delete GraphitiState for a session.

    Args:
        session_id: Session identifier

    Returns:
        True if state was deleted, False if not found
    """
    if session_id in _state_registry:
        del _state_registry[session_id]
        logger.info("Deleted session state: %s", session_id)
        return True
    return False


def cleanup_stale_states(max_age_hours: int = 24) -> int:
    """
    Clean up session states older than max_age_hours.

    Args:
        max_age_hours: Maximum age in hours before state is considered stale

    Returns:
        Number of states cleaned up
    """
    now = datetime.now(UTC)
    stale_sessions = [
        sid
        for sid, state in _state_registry.items()
        if (now - state.created_at).total_seconds() / 3600 > max_age_hours
    ]

    for sid in stale_sessions:
        del _state_registry[sid]

    if stale_sessions:
        logger.info("Cleaned up %d stale session states", len(stale_sessions))

    return len(stale_sessions)
