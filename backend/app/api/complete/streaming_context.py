"""Stream context dataclass shared across streaming submodules."""

from __future__ import annotations

import asyncio

from .schemas import MessageInput


class StreamContext:
    """Holds context needed while iterating stream events."""

    __slots__ = (
        "_seq", "agent_used", "cancel_event", "fallback_used", "is_new_session",
        "is_one_shot", "model", "model_used", "project_id", "provider", "session_id",
        "stream_start", "user_messages",
    )

    def __init__(
        self,
        session_id: str,
        model: str,
        provider: str,
        agent_used: str | None,
        model_used: str | None,
        fallback_used: bool,
        user_messages: list[MessageInput] | None,
        stream_start: float,
        is_new_session: bool,
        is_one_shot: bool,
        cancel_event: asyncio.Event | None = None,
        project_id: str | None = None,
    ) -> None:
        self._seq = 0
        self.session_id = session_id
        self.model = model
        self.provider = provider
        self.agent_used = agent_used
        self.model_used = model_used
        self.fallback_used = fallback_used
        self.user_messages = user_messages
        self.stream_start = stream_start
        self.is_new_session = is_new_session
        self.is_one_shot = is_one_shot
        self.cancel_event = cancel_event
        self.project_id = project_id

    def next_seq(self) -> int:
        """Return the next monotonic sequence number."""
        self._seq += 1
        return self._seq
