"""Session data transformations."""

from collections import defaultdict
from pathlib import Path
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
from app.services.tools.project_env import detect_main_repo


def _resolve_model_display_name(model_id: str | None) -> str | None:
    """Resolve model ID to human-readable name from catalog."""
    if not model_id:
        return None
    # Handle provider-prefixed IDs like "cloudcode/claude-sonnet-4-6"
    normalized = model_id.split("/")[-1] if "/" in model_id else model_id
    entry = MODEL_CATALOG_BY_ID.get(normalized) or MODEL_CATALOG_BY_ID.get(model_id)
    return entry.name if entry else None


def _session_metadata(session: Session) -> dict[str, Any]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else None
    return metadata or {}


def _requested_model(session: Session) -> str:
    metadata = _session_metadata(session)
    value = metadata.get("requested_model")
    if isinstance(value, str) and value:
        return value
    models_used = session.models_used or []
    if models_used:
        return models_used[0]
    return session.model


def _effective_model(session: Session) -> str:
    metadata = _session_metadata(session)
    value = metadata.get("effective_model")
    if isinstance(value, str) and value:
        return value
    models_used = session.models_used or []
    if models_used:
        return models_used[-1]
    return session.model


def _requested_provider(session: Session, requested_model: str) -> str:
    metadata = _session_metadata(session)
    value = metadata.get("requested_provider")
    if isinstance(value, str) and value:
        return value
    providers_used = session.providers_used or []
    if providers_used:
        return providers_used[0]
    return get_provider_for_model(requested_model)


def _effective_provider(session: Session, effective_model: str) -> str:
    metadata = _session_metadata(session)
    value = metadata.get("effective_provider")
    if isinstance(value, str) and value:
        return value
    providers_used = session.providers_used or []
    if providers_used:
        return providers_used[-1]
    return get_provider_for_model(effective_model)


def _fallback_used(session: Session, requested_model: str, effective_model: str) -> bool:
    metadata = _session_metadata(session)
    fallback_value = metadata.get("fallback_used")
    if isinstance(fallback_value, bool):
        return fallback_value
    return requested_model != effective_model


def _fallback_reason(session: Session) -> str | None:
    metadata = _session_metadata(session)
    value = metadata.get("fallback_reason")
    return value if isinstance(value, str) and value else None


def convert_messages_to_response(
    events: list[Any],
    agent_display_names: dict[str, str] | None = None,
) -> list[MessageResponse]:
    """Convert session events to message responses with thinking and tool data.

    Groups events by turn. For each turn, attaches thinking content and tool
    executions to the corresponding assistant message. User/system messages
    are returned as-is.

    Args:
        events: List of SessionEvent objects (all types)
        agent_display_names: Optional mapping of agent_id/slug to display name

    Returns:
        List of MessageResponse schemas with enriched assistant messages
    """
    MESSAGE_TYPES = {
        SessionEventType.USER_MESSAGE,
        SessionEventType.ASSISTANT_MESSAGE,
        SessionEventType.SYSTEM_MESSAGE,
    }
    names = agent_display_names or {}

    # Group events by turn
    turns: dict[int, list[Any]] = defaultdict(list)
    for e in events:
        turns[e.turn].append(e)

    result: list[MessageResponse] = []

    for turn_num in sorted(turns):
        turn_events = sorted(turns[turn_num], key=lambda x: x.sequence)

        # Collect thinking and tool data for this turn
        thinking_parts: list[str] = []
        thinking_tokens: int = 0
        tool_executions: list[ToolExecutionResponse] = []
        # Track tool_use events to pair with results
        tool_use_map: dict[str, ToolExecutionResponse] = {}

        for evt in turn_events:
            if evt.event_type == SessionEventType.THINKING:
                if evt.content:
                    thinking_parts.append(evt.content)
                if evt.tokens:
                    thinking_tokens += evt.tokens

            elif evt.event_type == SessionEventType.TOOL_USE:
                tool_resp = ToolExecutionResponse(
                    id=str(evt.id),
                    name=evt.tool_name or "unknown",
                    input=evt.tool_input,
                    status="complete",
                    duration_ms=evt.duration_ms,
                )
                tool_executions.append(tool_resp)
                if evt.tool_name:
                    tool_use_map[evt.tool_name] = tool_resp

            elif evt.event_type == SessionEventType.TOOL_RESULT:
                # Pair result with its tool_use event
                matched = tool_use_map.get(evt.tool_name or "")
                if matched:
                    output = evt.tool_output or evt.content
                    matched.result = str(output) if output else None
                    if evt.duration_ms:
                        matched.duration_ms = evt.duration_ms

        # Emit message events, enriching assistant messages
        for evt in turn_events:
            if evt.event_type not in MESSAGE_TYPES:
                continue

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

            # Attach thinking and tools to assistant messages
            if evt.event_type == SessionEventType.ASSISTANT_MESSAGE:
                if thinking_parts:
                    msg.thinking = "\n".join(thinking_parts)
                if thinking_tokens:
                    msg.thinking_tokens = thinking_tokens
                if tool_executions:
                    msg.tool_executions = tool_executions

            result.append(msg)

    return result


def build_session_list_items(
    sessions: list[Session],
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
) -> list[SessionListItem]:
    """Build list of session items with statistics.

    Args:
        sessions: List of session models
        msg_counts: Message counts by session ID
        token_stats: Token statistics by session ID

    Returns:
        List of SessionListItem schemas
    """
    def _optional_str(value: object) -> str | None:
        return value if isinstance(value, str) else None

    def _working_dir(session: Session) -> str | None:
        metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else None
        cwd = metadata.get("cwd") if metadata else None
        return cwd if isinstance(cwd, str) and cwd else None

    def _is_worktree(working_dir: str | None) -> bool:
        if not working_dir:
            return False
        try:
            return detect_main_repo(Path(working_dir).resolve()) is not None
        except OSError:
            return False

    return [
        SessionListItem(
            id=s.id,
            project_id=s.project_id,
            provider=effective_provider,
            model=effective_model,
            requested_provider=requested_provider,
            requested_model=requested_model,
            effective_provider=effective_provider,
            effective_model=effective_model,
            requested_model_display_name=_resolve_model_display_name(requested_model),
            effective_model_display_name=_resolve_model_display_name(effective_model),
            fallback_used=_fallback_used(s, requested_model, effective_model),
            fallback_reason=_fallback_reason(s),
            status=s.status,
            agent_slug=_optional_str(s.agent_slug),
            session_type=s.session_type or "completion",
            parent_session_id=_optional_str(s.parent_session_id),
            external_id=_optional_str(s.external_id),
            current_branch=_optional_str(s.current_branch),
            working_dir=working_dir,
            is_worktree=_is_worktree(working_dir),
            workstream_status=_optional_str(s.workstream_status),
            summary_oneliner=_optional_str(s.summary_oneliner),
            live_activity=build_live_activity_response(s),
            message_count=msg_counts.get(s.id, 0),
            total_input_tokens=token_stats.get(s.id, {}).get("input", 0),
            total_output_tokens=token_stats.get(s.id, {}).get("output", 0),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
        for requested_model in [_requested_model(s)]
        for effective_model in [_effective_model(s)]
        for requested_provider in [_requested_provider(s, requested_model)]
        for effective_provider in [_effective_provider(s, effective_model)]
        for working_dir in [_working_dir(s)]
    ]


def build_session_response(
    session: Session,
    messages: list[MessageResponse] | None = None,
    context_usage: ContextUsageResponse | None = None,
    agent_breakdown: list[AgentTokenBreakdown] | None = None,
    total_input: int = 0,
    total_output: int = 0,
) -> SessionResponse:
    """Build a SessionResponse from session data.

    Args:
        session: Session model
        messages: Optional list of messages
        context_usage: Optional context usage info
        agent_breakdown: Optional agent token breakdown
        total_input: Total input tokens
        total_output: Total output tokens

    Returns:
        SessionResponse schema
    """
    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=_effective_provider(session, _effective_model(session)),
        model=_effective_model(session),
        requested_provider=_requested_provider(session, _requested_model(session)),
        requested_model=_requested_model(session),
        effective_provider=_effective_provider(session, _effective_model(session)),
        effective_model=_effective_model(session),
        requested_model_display_name=_resolve_model_display_name(_requested_model(session)),
        effective_model_display_name=_resolve_model_display_name(_effective_model(session)),
        fallback_used=_fallback_used(session, _requested_model(session), _effective_model(session)),
        fallback_reason=_fallback_reason(session),
        status=session.status,
        agent_slug=session.agent_slug,
        session_type=session.session_type or "completion",
        created_at=session.created_at,
        updated_at=session.updated_at,
        live_activity=build_live_activity_response(session),
        messages=messages or [],
        context_usage=context_usage,
        agent_token_breakdown=agent_breakdown or [],
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
