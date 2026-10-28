"""Private helpers for transforming session events into message responses."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from app.models.session import SessionEventType
from app.services._session_metadata_helpers import resolve_model_display_name
from app.services.event_storage import TOOL_RESULT_SUMMARY_CHARS, _extract_tool_result_content

if TYPE_CHECKING:
    from app.api.schemas.sessions import MessageResponse, ToolExecutionResponse

_MESSAGE_TYPES = frozenset({
    SessionEventType.USER_MESSAGE,
    SessionEventType.ASSISTANT_MESSAGE,
    SessionEventType.SYSTEM_MESSAGE,
})


_TRACE_TYPES = frozenset({
    SessionEventType.THINKING,
    SessionEventType.TOOL_USE,
    SessionEventType.TOOL_RESULT,
})


def tool_execution_from_event(evt: Any) -> ToolExecutionResponse:
    from app.api.schemas.sessions import ToolExecutionResponse

    return ToolExecutionResponse(
        id=str(evt.id),
        name=evt.tool_name or "unknown",
        input=evt.tool_input,
        status="complete",
        duration_ms=evt.duration_ms,
    )


def _result_summary(evt: Any) -> str | None:
    """Readable, bounded text of a tool result, so a reopened chat does not carry whole file reads."""
    text = evt.content if isinstance(evt.content, str) and evt.content else None
    output = evt.tool_output
    if text is None and isinstance(output, dict):
        text = _extract_tool_result_content(output, TOOL_RESULT_SUMMARY_CHARS + 1)
        if text is None and output:
            text = json.dumps(output, default=str)
    elif text is None and output:
        text = str(output)
    if not text:
        return None
    if len(text) > TOOL_RESULT_SUMMARY_CHARS:
        return f"{text[:TOOL_RESULT_SUMMARY_CHARS]}…"
    return text


def apply_tool_result(
    evt: Any,
    tool_use_map: dict[str, list[ToolExecutionResponse]],
    pending: dict[str, ToolExecutionResponse] | None = None,
) -> None:
    """Attach a result to its call: by the call's own id when both carry one, else the first unanswered call of that name."""
    call_id = getattr(evt, "call_id", None)
    matched = pending.pop(call_id, None) if pending is not None and call_id else None
    if matched is None:
        queue = tool_use_map.get(evt.tool_name or "") or []
        matched = next((tool for tool in queue if tool.result is None and tool.status != "error"), None)
    if matched is None:
        return
    matched.result = _result_summary(evt)
    matched.duration_ms = evt.duration_ms or matched.duration_ms
    output = evt.tool_output
    if isinstance(output, dict) and output.get("is_error") is True:
        matched.status = "error"


def collect_turn_data(
    turn_events: list[Any],
) -> tuple[list[str], int, list[ToolExecutionResponse]]:
    thinking_parts: list[str] = []
    thinking_tokens = 0
    tool_executions: list[ToolExecutionResponse] = []
    tool_use_map: dict[str, list[ToolExecutionResponse]] = defaultdict(list)
    by_call_id: dict[str, ToolExecutionResponse] = {}

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
                tool_use_map[evt.tool_name].append(tool_resp)
            call_id = getattr(evt, "call_id", None)
            if call_id:
                by_call_id[call_id] = tool_resp
            continue
        if evt.event_type == SessionEventType.TOOL_RESULT:
            apply_tool_result(evt, tool_use_map, by_call_id)

    return thinking_parts, thinking_tokens, tool_executions


def build_message_response(
    evt: Any,
    names: dict[str, str],
    thinking_parts: list[str],
    thinking_tokens: int,
    tool_executions: list[ToolExecutionResponse],
) -> MessageResponse:
    from app.api.schemas.sessions import MessageResponse

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
    """Summarize turn that emitted tool activity but never persisted final assistant message."""
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
    """Build synthetic assistant message for turns missing persisted assistant event."""
    if not turn_events or not (thinking_parts or tool_executions):
        return None
    from app.api.schemas.sessions import MessageResponse

    source_evt = next(
        (
            evt
            for evt in reversed(turn_events)
            if getattr(evt, "agent_id", None) or getattr(evt, "agent_name", None)
        ),
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


def _split_at_user_messages(turn_events: list[Any]) -> list[list[Any]]:
    """A chat session keeps every exchange in one turn number; each user message starts a new exchange."""
    segments: list[list[Any]] = [[]]
    for evt in turn_events:
        if evt.event_type == SessionEventType.USER_MESSAGE and any(
            e.event_type in _MESSAGE_TYPES or e.event_type in _TRACE_TYPES for e in segments[-1]
        ):
            segments.append([])
        segments[-1].append(evt)
    return [segment for segment in segments if segment]


def turn_messages(turn_events: list[Any], names: dict[str, str]) -> list[MessageResponse]:
    messages: list[MessageResponse] = []
    for segment in _split_at_user_messages(turn_events):
        messages.extend(_exchange_messages(segment, names))
    return messages


def _exchange_messages(turn_events: list[Any], names: dict[str, str]) -> list[MessageResponse]:
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
