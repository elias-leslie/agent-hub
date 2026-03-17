"""Session data transformations."""

from collections import defaultdict
from typing import Any

from app.api.schemas.sessions import (
    AgentTokenBreakdown,
    ContextUsageResponse,
    MessageResponse,
    SessionListItem,
    SessionResponse,
    ToolExecutionResponse,
)
from app.constants.catalog import MODEL_CATALOG_BY_ID
from app.models import Session
from app.models.session import SessionEventType
from app.services.agent_routing import get_provider_for_model
from app.services.session_live_activity import build_live_activity_response
from app.services.tools.project_env import is_worktree_path

_MESSAGE_TYPES = frozenset({
    SessionEventType.USER_MESSAGE,
    SessionEventType.ASSISTANT_MESSAGE,
    SessionEventType.SYSTEM_MESSAGE,
})


def _resolve_model_display_name(model_id: str | None) -> str | None:
    if not model_id:
        return None
    normalized = model_id.split("/")[-1] if "/" in model_id else model_id
    entry = MODEL_CATALOG_BY_ID.get(normalized) or MODEL_CATALOG_BY_ID.get(model_id)
    return entry.name if entry else None


def _session_metadata(session: Session) -> dict[str, Any]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else None
    return metadata or {}


def _metadata_value(session: Session, key: str) -> str | None:
    value = _session_metadata(session).get(key)
    return value if isinstance(value, str) and value else None


def _list_first(values: object) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    first = values[0]
    return first if isinstance(first, str) else None


def _list_last(values: object) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    last = values[-1]
    return last if isinstance(last, str) else None


def _requested_model(session: Session) -> str:
    return _metadata_value(session, "requested_model") or _list_first(session.models_used) or str(session.model)


def _effective_model(session: Session) -> str:
    return _metadata_value(session, "effective_model") or _list_last(session.models_used) or str(session.model)


def _requested_provider(session: Session, requested_model: str) -> str:
    return (
        _metadata_value(session, "requested_provider")
        or _list_first(session.providers_used)
        or get_provider_for_model(requested_model)
    )


def _effective_provider(session: Session, effective_model: str) -> str:
    return (
        _metadata_value(session, "effective_provider")
        or _list_last(session.providers_used)
        or get_provider_for_model(effective_model)
    )


def _fallback_used(session: Session, requested_model: str, effective_model: str) -> bool:
    fallback_value = _session_metadata(session).get("fallback_used")
    return fallback_value if isinstance(fallback_value, bool) else requested_model != effective_model


def _fallback_reason(session: Session) -> str | None:
    return _metadata_value(session, "fallback_reason")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _scope_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _working_dir(session: Session) -> str | None:
    return _metadata_value(session, "worktree_path") or _metadata_value(session, "cwd")


def _repo_root(session: Session) -> str | None:
    return _metadata_value(session, "repo_root")


def _worktree_path(session: Session) -> str | None:
    return _metadata_value(session, "worktree_path") or _metadata_value(session, "cwd")


_is_worktree = is_worktree_path


def _tool_execution_from_event(evt: Any) -> ToolExecutionResponse:
    return ToolExecutionResponse(
        id=str(evt.id),
        name=evt.tool_name or "unknown",
        input=evt.tool_input,
        status="complete",
        duration_ms=evt.duration_ms,
    )


def _apply_tool_result(
    evt: Any,
    tool_use_map: dict[str, ToolExecutionResponse],
) -> None:
    matched = tool_use_map.get(evt.tool_name or "")
    if not matched:
        return
    output = evt.tool_output or evt.content
    matched.result = str(output) if output else None
    matched.duration_ms = evt.duration_ms or matched.duration_ms


def _collect_turn_data(
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
            tool_resp = _tool_execution_from_event(evt)
            tool_executions.append(tool_resp)
            if evt.tool_name:
                tool_use_map[evt.tool_name] = tool_resp
            continue
        if evt.event_type == SessionEventType.TOOL_RESULT:
            _apply_tool_result(evt, tool_use_map)

    return thinking_parts, thinking_tokens, tool_executions


def _build_message_response(
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
        model_display_name=_resolve_model_display_name(evt.model_used),
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


def _group_events_by_turn(events: list[Any]) -> dict[int, list[Any]]:
    turns: dict[int, list[Any]] = defaultdict(list)
    for event in events:
        turns[event.turn].append(event)
    return turns


def _turn_messages(
    turn_events: list[Any],
    names: dict[str, str],
) -> list[MessageResponse]:
    thinking_parts, thinking_tokens, tool_executions = _collect_turn_data(turn_events)
    messages: list[MessageResponse] = []
    for evt in turn_events:
        if evt.event_type not in _MESSAGE_TYPES:
            continue
        messages.append(
            _build_message_response(evt, names, thinking_parts, thinking_tokens, tool_executions)
        )
    return messages


def convert_messages_to_response(
    events: list[Any],
    agent_display_names: dict[str, str] | None = None,
) -> list[MessageResponse]:
    names = agent_display_names or {}
    turns = _group_events_by_turn(events)
    result: list[MessageResponse] = []
    for turn_num in sorted(turns):
        turn_events = sorted(turns[turn_num], key=lambda event: event.sequence)
        result.extend(_turn_messages(turn_events, names))
    return result


def _session_model_info(session: Session) -> dict[str, str | bool | None]:
    requested_model = _requested_model(session)
    effective_model = _effective_model(session)
    return {
        "requested_model": requested_model,
        "effective_model": effective_model,
        "requested_provider": _requested_provider(session, requested_model),
        "effective_provider": _effective_provider(session, effective_model),
        "fallback_used": _fallback_used(session, requested_model, effective_model),
        "fallback_reason": _fallback_reason(session),
    }


def _session_list_item(
    session: Session,
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> SessionListItem:
    model_info = _session_model_info(session)
    working_dir = _working_dir(session)
    session_tokens = token_stats.get(session.id, {})
    return SessionListItem(
        id=session.id,
        project_id=session.project_id,
        provider=model_info["effective_provider"],
        model=model_info["effective_model"],
        requested_provider=model_info["requested_provider"],
        requested_model=model_info["requested_model"],
        effective_provider=model_info["effective_provider"],
        effective_model=model_info["effective_model"],
        requested_model_display_name=_resolve_model_display_name(model_info["requested_model"]),
        effective_model_display_name=_resolve_model_display_name(model_info["effective_model"]),
        fallback_used=model_info["fallback_used"],
        fallback_reason=model_info["fallback_reason"],
        status=session.status,
        agent_slug=_optional_str(session.agent_slug),
        session_type=session.session_type or "completion",
        parent_session_id=_optional_str(session.parent_session_id),
        external_id=_optional_str(session.external_id),
        current_branch=_optional_str(session.current_branch),
        working_dir=working_dir,
        repo_root=_repo_root(session),
        worktree_path=_worktree_path(session),
        host=_metadata_value(session, "host"),
        tmux_session_name=_metadata_value(session, "tmux_session_name"),
        tmux_pane_id=_metadata_value(session, "tmux_pane_id"),
        is_worktree=_is_worktree(working_dir),
        workstream_status=_optional_str(session.workstream_status),
        summary_oneliner=_optional_str(session.summary_oneliner),
        declared_scope_paths=_scope_list(session.declared_scope_paths),
        observed_read_paths=_scope_list(session.observed_read_paths),
        observed_write_paths=_scope_list(session.observed_write_paths),
        scope_confidence=_optional_str(session.scope_confidence),
        live_activity=build_live_activity_response(
            session,
            has_owner_lane=session.id in (owner_session_ids or set()),
            has_specialist_lane=session.id in (specialist_session_ids or set()),
        ),
        message_count=msg_counts.get(session.id, 0),
        total_input_tokens=session_tokens.get("input", 0),
        total_output_tokens=session_tokens.get("output", 0),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def build_session_list_items(
    sessions: list[Session],
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> list[SessionListItem]:
    return [
        _session_list_item(
            session,
            msg_counts,
            token_stats,
            owner_session_ids=owner_session_ids,
            specialist_session_ids=specialist_session_ids,
        )
        for session in sessions
    ]


def build_session_response(
    session: Session,
    messages: list[MessageResponse] | None = None,
    context_usage: ContextUsageResponse | None = None,
    agent_breakdown: list[AgentTokenBreakdown] | None = None,
    total_input: int = 0,
    total_output: int = 0,
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> SessionResponse:
    model_info = _session_model_info(session)
    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=model_info["effective_provider"],
        model=model_info["effective_model"],
        requested_provider=model_info["requested_provider"],
        requested_model=model_info["requested_model"],
        effective_provider=model_info["effective_provider"],
        effective_model=model_info["effective_model"],
        requested_model_display_name=_resolve_model_display_name(model_info["requested_model"]),
        effective_model_display_name=_resolve_model_display_name(model_info["effective_model"]),
        fallback_used=model_info["fallback_used"],
        fallback_reason=model_info["fallback_reason"],
        status=session.status,
        agent_slug=session.agent_slug,
        session_type=session.session_type or "completion",
        external_id=_optional_str(session.external_id),
        current_branch=_optional_str(session.current_branch),
        working_dir=_working_dir(session),
        repo_root=_repo_root(session),
        worktree_path=_worktree_path(session),
        host=_metadata_value(session, "host"),
        tmux_session_name=_metadata_value(session, "tmux_session_name"),
        tmux_pane_id=_metadata_value(session, "tmux_pane_id"),
        declared_scope_paths=_scope_list(session.declared_scope_paths),
        observed_read_paths=_scope_list(session.observed_read_paths),
        observed_write_paths=_scope_list(session.observed_write_paths),
        scope_confidence=_optional_str(session.scope_confidence),
        created_at=session.created_at,
        updated_at=session.updated_at,
        live_activity=build_live_activity_response(
            session,
            has_owner_lane=session.id in (owner_session_ids or set()),
            has_specialist_lane=session.id in (specialist_session_ids or set()),
        ),
        messages=messages or [],
        context_usage=context_usage,
        agent_token_breakdown=agent_breakdown or [],
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
