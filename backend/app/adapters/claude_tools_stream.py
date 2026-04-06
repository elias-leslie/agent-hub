"""Claude SDK stream session and message-loop utilities."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.adapters._claude_result_metadata import (
    normalized_stop_reason,
    resolve_result_finish_reason,
)
from app.adapters.claude_tools_query_session import (
    _ClaudeSDKQuerySession,
)
from app.adapters.claude_utils import _sdk_semaphore

logger = logging.getLogger(__name__)


@dataclass
class ResultMessage:
    """Fallback terminal message when the Claude SDK omits its final result frame."""

    subtype: str = "success"
    duration_ms: int = 0
    duration_api_ms: int = 0
    is_error: bool = False
    num_turns: int = 0
    session_id: str | None = None
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    finish_reason: str | None = None


@dataclass
class ErrorMessage:
    """Terminal message carrying a tool-stream error without raising through the iterator."""

    error: str


def _resolve_result_message(
    message: Any,
    session_id: str | None,
    configured_max_turns: int | None,
) -> Any:
    """Annotate or reconstruct a ResultMessage with resolved finish/stop reasons."""
    resolved_finish_reason = resolve_result_finish_reason(
        message,
        configured_max_turns=configured_max_turns,
    )
    resolved_stop_reason = normalized_stop_reason(
        message,
        configured_max_turns=configured_max_turns,
    )
    try:
        message.finish_reason = resolved_finish_reason
        if resolved_stop_reason is not None:
            message.stop_reason = resolved_stop_reason
    except Exception:
        logger.debug("Failed to set finish_reason on SDK message, reconstructing", exc_info=True)
        message = ResultMessage(
            session_id=session_id,
            subtype=getattr(message, "subtype", "success"),
            stop_reason=resolved_stop_reason,
            finish_reason=resolved_finish_reason,
            result=getattr(message, "result", None),
            usage=getattr(message, "usage", None),
            structured_output=getattr(message, "structured_output", None),
            total_cost_usd=getattr(message, "total_cost_usd", None),
            num_turns=getattr(message, "num_turns", 0),
            is_error=getattr(message, "is_error", False),
            duration_ms=getattr(message, "duration_ms", 0),
            duration_api_ms=getattr(message, "duration_api_ms", 0),
        )
    return message


@dataclass
class _ClaudeSDKMessageStreamSession:
    """Own Claude SDK iterator state for one streamed tool session."""

    prompt: str | Any
    options: Any
    session_id: str | None = None
    done_emitted: bool = False
    saw_payload: bool = False
    configured_max_turns: int | None = None
    iterator_closed: bool = False

    def __post_init__(self) -> None:
        self.configured_max_turns = getattr(self.options, "max_turns", None)
        self.query_session = _ClaudeSDKQuerySession(self.prompt, self.options)

    async def _close_iterator(self) -> None:
        await self.query_session.close()
        self.iterator_closed = True

    async def interrupt(self) -> None:
        """Interrupt the active SDK query session."""
        with suppress(asyncio.CancelledError):
            await self.query_session.interrupt()

    async def close(self) -> None:
        """Close the active SDK query session once."""
        if self.iterator_closed:
            return
        await self._close_iterator()

    async def _iterate_messages(
        self, message_iter: Any
    ) -> AsyncGenerator[tuple[Any, str | None]]:
        """Process and yield normalized (message, session_id) pairs."""
        async for message in message_iter:
            if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                self.session_id = message.data.get("session_id")
                if self.session_id:
                    logger.info("Claude SDK session ID: %s", self.session_id)
                continue
            if type(message).__name__ == "ResultMessage":
                message = _resolve_result_message(message, self.session_id, self.configured_max_turns)
                yield (message, self.session_id)
                self.done_emitted = True
                await self._close_iterator()
                return
            if not self.done_emitted:
                self.saw_payload = True
                yield (message, self.session_id)
        if self.saw_payload and not self.done_emitted:
            finish_reason = "end_turn"
            logger.warning(
                "Claude SDK stream ended without ResultMessage; synthesizing terminal result (%s)",
                finish_reason,
            )
            yield (
                ResultMessage(
                    session_id=self.session_id,
                    stop_reason=finish_reason,
                    finish_reason=finish_reason,
                ),
                self.session_id,
            )
        await self._close_iterator()

    async def iterate(self) -> AsyncGenerator[tuple[Any, str | None]]:
        """Yield (message, session_id) pairs while owning iterator cleanup."""
        await self.query_session.start()
        message_iter = self.query_session.message_iter
        if message_iter is None:
            raise RuntimeError("Claude SDK query session did not initialize an iterator")
        try:
            async for item in self._iterate_messages(message_iter):
                yield item
        finally:
            if not self.iterator_closed:
                await self.query_session.close()
                self.iterator_closed = True


async def _iterate_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncGenerator[tuple[Any, str | None]]:
    """Core message-processing loop over the claude_agent_sdk query iterator."""
    del provider_name  # Reserved for future per-provider streaming specialization.
    session = _ClaudeSDKMessageStreamSession(prompt=prompt, options=options)
    session_iter = session.iterate()
    try:
        async for item in session_iter:
            yield item
    finally:
        with suppress(asyncio.CancelledError):
            await session_iter.aclose()


async def _run_sdk_stream_loop(
    inner_iter: Any,
) -> AsyncGenerator[tuple[Any, str | None]]:
    """Yield from inner_iter with error capture and conditional close.

    Skips aclose after natural exhaustion: the Claude SDK iterator unwind can
    inject cancellation into the current task, corrupting downstream final
    response persistence.
    """
    exhausted = False
    try:
        async for item in inner_iter:
            yield item
        exhausted = True
    except Exception as e:
        error_msg = f"Claude tool error: {e}"
        logger.error(error_msg)
        yield (ErrorMessage(error=error_msg), None)
    finally:
        if not exhausted:
            await inner_iter.aclose()


async def _stream_sdk_session_messages(
    session: _ClaudeSDKMessageStreamSession,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from an owned SDK message session."""
    del provider_name  # Reserved for future per-provider streaming specialization.
    async with _sdk_semaphore:
        run_loop = _run_sdk_stream_loop(session.iterate())
        try:
            async for item in run_loop:
                yield item
        finally:
            await run_loop.aclose()
