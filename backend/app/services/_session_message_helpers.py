"""Private helpers for transforming session events into message responses."""

from collections import defaultdict
from typing import Any

from app.api.schemas.sessions import MessageResponse, ToolExecutionResponse
from app.models.session import SessionEventType
from app.services._session_metadata_helpers import resolve_model_display_name

_MESSAGE_TYPES = frozenset({
    SessionEventType.USER_MESSAGE,
    SessionEventType.ASSISTANT_MESSAGE,
    SessionEventType.SYSTEM_MESSAGE,
})


def tool_execution_from_event(evt: Any) -> ToolExecutionResponse:
    return ToolExecutionResponse(
        id=str(evt.id),
        name=evt.tool_name or "unknown",
        input=evt.tool_input,
        status="complete",
        duration_ms=evt.duration_ms,
    )


def apply_tool_result(evt: Any, tool_use_map: dict[str, ToolExecutionResponse]) -> None:
    matched = tool_use_map.get(evt.tool_name or "")
    if not matched:
        return
    output = evt.tool_output or evt.content
    matched.result = str(output) if output else None
    matched.duration_ms = evt.duration_ms or matched.duration_ms


def collect_turn_data(
    turn_events: list[Any],
) -> tuple[list[str], int, list[ToolExecutionResponse]]:
    thinking_parts: list[str] = []
    thinking_tokens = 0
    tool_executions: list[ToolExecutionResponse] = []
    tool_use_map: dict[str, ToolExecutionResponse] = {}

    for evt in turn_events:
        if evt.event_type == SessionEventType.THINKING:
            if evt.content:
                thinking_parts.append(evt.content)
            if evt.tokens:
                thinking_tokens += evt.tokens
            continue
        if evt.event_type == SessionEventType.TOOL_USE:
            tool_resp = tool_execution_from_event(evt)
            tool_executions.append(tool_resp)
            if evt.tool_name:
                tool_use_map[evt.tool_name] = tool_resp
            continue
        if evt.event_type == SessionEventType.TOOL_RESULT:
            apply_tool_result(evt, tool_use_map)

    return thinking_parts, thinking_tokens, tool_executions


def build_message_response(
    evt: Any,
    names: dict[str, str],
    thinking_parts: list[str],
    thinking_tokens: int,
    tool_executions: list[ToolExecutionResponse],
) -> MessageResponse:
    msg = MessageResponse(
        id=str(evt.id),
        role=evt.role,
        content=evt.content,
        tokens=evt.tokens,
        agent_id=evt.agent_id,
        agent_name=evt.agent_name,
        model_used=evt.model_used,
        model_display_name=resolve_model_display_name(evt.model_used),
        agent_display_name=names.get(evt.agent_id or "") or names.get(evt.agent_name or ""),
        created_at=evt.created_at,
    )
    if evt.event_type != SessionEventType.ASSISTANT_MESSAGE:
        return msg
    if thinking_parts:
        msg.thinking = "\n".join(thinking_parts)
    if thinking_tokens:
        msg.thinking_tokens = thinking_tokens
    if tool_executions:
        msg.tool_executions = tool_executions
    return msg


def group_events_by_turn(events: list[Any]) -> dict[int, list[Any]]:
    turns: dict[int, list[Any]] = defaultdict(list)
    for event in events:
        turns[event.turn].append(event)
    return turns


def turn_messages(turn_events: list[Any], names: dict[str, str]) -> list[MessageResponse]:
    thinking_parts, thinking_tokens, tool_executions = collect_turn_data(turn_events)
    messages: list[MessageResponse] = []
    for evt in turn_events:
        if evt.event_type not in _MESSAGE_TYPES:
            continue
        messages.append(
            build_message_response(evt, names, thinking_parts, thinking_tokens, tool_executions)
        )
    return messages
