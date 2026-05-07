"""Stream context dataclass shared across streaming submodules."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from .schemas import MessageInput


class StreamContext:
    """Holds context needed while iterating stream events."""

    _active_contexts: ClassVar[dict[str, StreamContext]] = {}

    __slots__ = (
        "_seq", "agent_used", "auto_candidate_model_id", "cancel_event",
        "fallback_used", "is_new_session", "is_one_shot", "last_progress_at",
        "last_progress_chars", "model", "model_used", "project_id", "provider",
        "routing_canary_percent", "routing_decision_id", "routing_mode",
        "session_id", "source_metadata", "stream_start", "user_messages",
        "workload_profile",
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
        source_metadata: dict[str, object] | None = None,
        routing_mode: str | None = None,
        workload_profile: str | None = None,
        routing_decision_id: str | None = None,
        auto_candidate_model_id: str | None = None,
        routing_canary_percent: float | None = None,
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
        self.source_metadata = source_metadata
        self.routing_mode = routing_mode
        self.workload_profile = workload_profile
        self.routing_decision_id = routing_decision_id
        self.auto_candidate_model_id = auto_candidate_model_id
        self.routing_canary_percent = routing_canary_percent
        self.last_progress_at = 0.0
        self.last_progress_chars = 0

    @classmethod
    def open(
        cls,
        *,
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
        project_id: str | None = None,
        source_metadata: dict[str, object] | None = None,
        routing_mode: str | None = None,
        workload_profile: str | None = None,
        routing_decision_id: str | None = None,
        auto_candidate_model_id: str | None = None,
        routing_canary_percent: float | None = None,
    ) -> StreamContext:
        """Create and register an active stream context for cooperative cancel."""
        ctx = cls(
            session_id=session_id,
            model=model,
            provider=provider,
            agent_used=agent_used,
            model_used=model_used,
            fallback_used=fallback_used,
            user_messages=user_messages,
            stream_start=stream_start,
            is_new_session=is_new_session,
            is_one_shot=is_one_shot,
            cancel_event=asyncio.Event(),
            project_id=project_id,
            source_metadata=source_metadata,
            routing_mode=routing_mode,
            workload_profile=workload_profile,
            routing_decision_id=routing_decision_id,
            auto_candidate_model_id=auto_candidate_model_id,
            routing_canary_percent=routing_canary_percent,
        )
        cls._active_contexts[session_id] = ctx
        return ctx

    @classmethod
    def cancel(cls, session_id: str) -> bool:
        """Signal an active streaming session to stop after the current boundary."""
        ctx = cls._active_contexts.get(session_id)
        if ctx is None or ctx.cancel_event is None:
            return False
        ctx.cancel_event.set()
        return True

    def close(self) -> None:
        """Unregister the active stream context."""
        self._active_contexts.pop(self.session_id, None)

    def next_seq(self) -> int:
        """Return the next monotonic sequence number."""
        self._seq += 1
        return self._seq

    def reset_progress_cursor(self) -> None:
        """Reset live-progress throttling at the start of a model turn."""
        self.last_progress_at = 0.0
        self.last_progress_chars = 0
