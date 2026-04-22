"""Session data transformations."""

from typing import Any

from app.api.schemas.sessions import (
    AgentTokenBreakdown,
    ContextUsageResponse,
    MessageResponse,
    SessionListItem,
    SessionResponse,
)
from app.models import Session, SessionEventType
from app.services._session_message_helpers import (
    group_events_by_turn,
    turn_messages,
)
from app.services._session_metadata_helpers import (
    effective_model,
    metadata_value,
    optional_str,
    repo_root,
    resolve_model_display_name,
    scope_list,
    session_attribution,
    session_model_info,
    source_client,
    source_path,
    working_dir,
)
from app.services.session_live_activity import build_live_activity_response
from app.services.session_scope import resolve_scope_confidence

# Re-export private helpers with underscore names for backward compatibility
_resolve_model_display_name = resolve_model_display_name
_metadata_value = metadata_value
_optional_str = optional_str
_scope_list = scope_list
_working_dir = working_dir
_repo_root = repo_root
_source_client = source_client
_source_path = source_path
_session_attribution = session_attribution
_session_model_info = session_model_info
_effective_model = effective_model


def convert_messages_to_response(
    events: list[Any],
    agent_display_names: dict[str, str] | None = None,
) -> list[MessageResponse]:
    names = agent_display_names or {}
    turns = group_events_by_turn(events)
    result: list[MessageResponse] = []
    for turn_num in sorted(turns):
        turn_events = sorted(turns[turn_num], key=lambda event: event.sequence)
        result.extend(turn_messages(turn_events, names))
    return result


def _resolved_scope_confidence(session: Session) -> str | None:
    return resolve_scope_confidence(
        None,
        scope_list(session.declared_scope_paths),
        scope_list(session.observed_write_paths),
        scope_list(session.observed_read_paths),
        optional_str(session.scope_confidence),
    )


def _message_count(events: list[Any]) -> int:
    return sum(
        1
        for event in events
        if getattr(event, "event_type", None) in {
            SessionEventType.USER_MESSAGE,
            SessionEventType.ASSISTANT_MESSAGE,
        }
    )


def _session_list_item(
    session: Session,
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
    event_counts: dict[str, int] | None = None,
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> SessionListItem:
    model_info = session_model_info(session)
    attribution = session_attribution(session)
    wd = working_dir(session)
    session_tokens = token_stats.get(session.id, {})
    provider_metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    batch_task_ids = [
        str(task_id).strip()
        for task_id in provider_metadata.get("batch_task_ids", [])
        if isinstance(task_id, str) and str(task_id).strip()
    ]
    return SessionListItem(
        id=session.id,
        project_id=session.project_id,
        provider=model_info["effective_provider"],
        model=model_info["effective_model"],
        requested_provider=model_info["requested_provider"],
        requested_model=model_info["requested_model"],
        effective_provider=model_info["effective_provider"],
        effective_model=model_info["effective_model"],
        requested_model_display_name=resolve_model_display_name(model_info["requested_model"]),
        effective_model_display_name=resolve_model_display_name(model_info["effective_model"]),
        fallback_used=model_info["fallback_used"],
        fallback_reason=model_info["fallback_reason"],
        status=session.status,
        agent_slug=optional_str(session.agent_slug),
        session_type=session.session_type or "completion",
        parent_session_id=optional_str(session.parent_session_id),
        external_id=optional_str(session.external_id),
        client_id=optional_str(session.client_id),
        request_source=optional_str(session.request_source),
        source_client=source_client(session),
        source_path=source_path(session),
        attribution_kind=optional_str(attribution.get("attribution_kind")),
        attribution_label=optional_str(attribution.get("attribution_label")),
        attribution_detail=optional_str(attribution.get("attribution_detail")),
        current_branch=optional_str(session.current_branch),
        working_dir=wd,
        repo_root=repo_root(session),
        host=metadata_value(session, "host"),
        tmux_session_name=metadata_value(session, "tmux_session_name"),
        tmux_pane_id=metadata_value(session, "tmux_pane_id"),
        workstream_status=optional_str(session.workstream_status),
        summary_oneliner=optional_str(session.summary_oneliner),
        batch_task_ids=batch_task_ids,
        declared_scope_paths=scope_list(session.declared_scope_paths),
        observed_read_paths=scope_list(session.observed_read_paths),
        observed_write_paths=scope_list(session.observed_write_paths),
        scope_confidence=_resolved_scope_confidence(session),
        live_activity=build_live_activity_response(
            session,
            has_owner_lane=session.id in (owner_session_ids or set()),
            has_specialist_lane=session.id in (specialist_session_ids or set()),
        ),
        message_count=msg_counts.get(session.id, 0),
        event_count=(event_counts or {}).get(session.id, 0),
        total_input_tokens=session_tokens.get("input", 0),
        total_output_tokens=session_tokens.get("output", 0),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def build_session_list_items(
    sessions: list[Session],
    msg_counts: dict[str, int],
    token_stats: dict[str, dict[str, int]],
    event_counts: dict[str, int] | None = None,
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> list[SessionListItem]:
    return [
        _session_list_item(
            session,
            msg_counts,
            token_stats,
            event_counts=event_counts,
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
    message_count: int | None = None,
    event_count: int | None = None,
    owner_session_ids: set[str] | None = None,
    specialist_session_ids: set[str] | None = None,
) -> SessionResponse:
    model_info = session_model_info(session)
    attribution = session_attribution(session)
    provider_metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    batch_task_ids = [
        str(task_id).strip()
        for task_id in provider_metadata.get("batch_task_ids", [])
        if isinstance(task_id, str) and str(task_id).strip()
    ]
    return SessionResponse(
        id=session.id,
        project_id=session.project_id,
        provider=model_info["effective_provider"],
        model=model_info["effective_model"],
        requested_provider=model_info["requested_provider"],
        requested_model=model_info["requested_model"],
        effective_provider=model_info["effective_provider"],
        effective_model=model_info["effective_model"],
        requested_model_display_name=resolve_model_display_name(model_info["requested_model"]),
        effective_model_display_name=resolve_model_display_name(model_info["effective_model"]),
        fallback_used=model_info["fallback_used"],
        fallback_reason=model_info["fallback_reason"],
        status=session.status,
        agent_slug=session.agent_slug,
        session_type=session.session_type or "completion",
        parent_session_id=optional_str(session.parent_session_id),
        external_id=optional_str(session.external_id),
        client_id=optional_str(session.client_id),
        request_source=optional_str(session.request_source),
        source_client=source_client(session),
        source_path=source_path(session),
        attribution_kind=optional_str(attribution.get("attribution_kind")),
        attribution_label=optional_str(attribution.get("attribution_label")),
        attribution_detail=optional_str(attribution.get("attribution_detail")),
        current_branch=optional_str(session.current_branch),
        working_dir=working_dir(session),
        repo_root=repo_root(session),
        host=metadata_value(session, "host"),
        tmux_session_name=metadata_value(session, "tmux_session_name"),
        tmux_pane_id=metadata_value(session, "tmux_pane_id"),
        workstream_status=optional_str(session.workstream_status),
        summary_oneliner=optional_str(session.summary_oneliner),
        batch_task_ids=batch_task_ids,
        declared_scope_paths=scope_list(session.declared_scope_paths),
        observed_read_paths=scope_list(session.observed_read_paths),
        observed_write_paths=scope_list(session.observed_write_paths),
        scope_confidence=_resolved_scope_confidence(session),
        created_at=session.created_at,
        updated_at=session.updated_at,
        live_activity=build_live_activity_response(
            session,
            has_owner_lane=session.id in (owner_session_ids or set()),
            has_specialist_lane=session.id in (specialist_session_ids or set()),
        ),
        message_count=message_count,
        event_count=event_count,
        messages=messages or [],
        context_usage=context_usage,
        agent_token_breakdown=agent_breakdown or [],
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
