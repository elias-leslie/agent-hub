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


def _build_incomplete_turn_content(tool_executions: list[ToolExecutionResponse]) -> str:
    """Summarize a turn that emitted tool activity but never persisted a final assistant message."""
    if not tool_executions:
        return "No final assistant summary persisted for this turn."
    tool_names = [tool.name for tool in tool_executions if tool.name]
    if not tool_names:
        return "Tool activity recorded, but no final assistant summary persisted."
    preview = ", ".join(tool_names[:3])
    if len(tool_names) > 3:
        preview = f"{preview}, +{len(tool_names) - 3} more"
    return f"Tool activity recorded without a final assistant summary. Tools: {preview}."


def build_incomplete_turn_response(
    turn_events: list[Any],
    names: dict[str, str],
    thinking_parts: list[str],
    thinking_tokens: int,
    tool_executions: list[ToolExecutionResponse],
) -> MessageResponse | None:
    """Build a synthetic assistant message for turns missing a persisted assistant event."""
    if not turn_events or not (thinking_parts or tool_executions):
        return None
    source_evt = next(
        (evt for evt in reversed(turn_events) if getattr(evt, "agent_id", None) or getattr(evt, "agent_name", None)),
        turn_events[-1],
    )
    msg = MessageResponse(
        id=f"{source_evt.id}-synthetic-assistant",
        role="assistant",
        content=_build_incomplete_turn_content(tool_executions),
        tokens=0,
        agent_id=source_evt.agent_id,
        agent_name=source_evt.agent_name,
        model_used=source_evt.model_used,
        model_display_name=resolve_model_display_name(source_evt.model_used),
        agent_display_name=names.get(source_evt.agent_id or "") or names.get(source_evt.agent_name or ""),
        created_at=source_evt.created_at,
    )
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
    has_assistant_message = any(message.role == "assistant" for message in messages)
    if not has_assistant_message:
        synthetic = build_incomplete_turn_response(
            turn_events,
            names,
            thinking_parts,
            thinking_tokens,
            tool_executions,
        )
        if synthetic is not None:
            messages.append(synthetic)
    return messages
