"""
Convenience functions for publishing session events.

Helper functions that wrap EventPublisher.publish() for common event types.
"""

from typing import Any

from .events_models import SessionEvent, SessionEventType


async def publish_session_start(
    session_id: str,
    model: str,
    project_id: str | None = None,
) -> None:
    """Helper to publish session_start event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.SESSION_START,
            session_id=session_id,
            data={
                "model": model,
                "project_id": project_id,
            },
        )
    )


async def publish_message(
    session_id: str,
    role: str,
    content: str,
    tokens: int | None = None,
) -> None:
    """Helper to publish message event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.MESSAGE,
            session_id=session_id,
            data={
                "role": role,
                "content": content,
                "tokens": tokens,
            },
        )
    )


async def publish_tool_use(
    session_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any | None = None,
) -> None:
    """Helper to publish tool_use event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.TOOL_USE,
            session_id=session_id,
            data={
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_output": tool_output,
            },
        )
    )


async def publish_tool_result(
    session_id: str,
    tool_name: str | None,
    tool_output: Any | None = None,
    *,
    duration_ms: int | None = None,
    is_error: bool | None = None,
) -> None:
    """Helper to publish tool_result event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_output": tool_output,
        "duration_ms": duration_ms,
    }
    if is_error is not None:
        payload["is_error"] = is_error
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.TOOL_RESULT,
            session_id=session_id,
            data=payload,
        )
    )


async def publish_complete(
    session_id: str,
    input_tokens: int,
    output_tokens: int,
    cost: float | None = None,
) -> None:
    """Helper to publish complete event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.COMPLETE,
            session_id=session_id,
            data={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
            },
        )
    )


async def publish_error(
    session_id: str,
    error_type: str,
    error_message: str,
) -> None:
    """Helper to publish error event."""
    from .events import get_event_publisher

    publisher = get_event_publisher()
    await publisher.publish(
        SessionEvent(
            event_type=SessionEventType.ERROR,
            session_id=session_id,
            data={
                "error_type": error_type,
                "error_message": error_message,
            },
        )
    )
