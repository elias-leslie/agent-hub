"""Completion operations for Agent Hub clients."""

from typing import Any

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import ClientDisabledError
from agent_hub.models import (
    CompletionResponse,
    MessageInput,
    RoutingConfig,
    ToolDefinition,
    ToolResultMessage,
)


def _normalize_messages(
    messages: list[dict[str, str] | MessageInput | ToolResultMessage],
) -> list[dict[str, Any]]:
    """Normalize messages to plain dicts."""
    result = []
    for msg in messages:
        if isinstance(msg, (MessageInput, ToolResultMessage)):
            result.append(msg.model_dump())
        else:
            result.append(msg)
    return result


def _normalize_tools(
    tools: list[dict[str, Any] | ToolDefinition] | None,
) -> list[dict[str, Any]] | None:
    """Normalize tools to plain dicts, or return None if no tools."""
    if not tools:
        return None
    result = []
    for tool in tools:
        if isinstance(tool, ToolDefinition):
            result.append(tool.model_dump())
        else:
            result.append(tool)
    return result


def _apply_identity_fields(
    payload: dict[str, Any],
    agent_slug: str | None,
    model: str | None,
    session_id: str | None,
    purpose: str | None,
    external_id: str | None,
    use_memory: bool,
    memory_group_id: str | None,
    routing_config: RoutingConfig | dict[str, Any] | None,
    tool_dicts: list[dict[str, Any]] | None,
    enable_programmatic_tools: bool,
) -> None:
    """Apply identity/routing optional fields to payload in-place."""
    if agent_slug:
        payload["agent_slug"] = agent_slug
    if model:
        payload["model"] = model
    if session_id:
        payload["session_id"] = session_id
    if purpose:
        payload["purpose"] = purpose
    if external_id:
        payload["external_id"] = external_id
    payload["use_memory"] = use_memory
    if memory_group_id:
        payload["memory_group_id"] = memory_group_id
    if routing_config:
        if isinstance(routing_config, RoutingConfig):
            payload["routing_config"] = routing_config.model_dump(exclude_none=True)
        else:
            payload["routing_config"] = routing_config
    if tool_dicts:
        payload["tools"] = tool_dicts
    if enable_programmatic_tools:
        payload["enable_programmatic_tools"] = True


def _apply_execution_fields(
    payload: dict[str, Any],
    container_id: str | None,
    max_turns: int,
    working_dir: str | None,
    execute_tools: bool,
    trace_id: str | None,
    timeout_seconds: float | None,
    thinking_level: str | None,
    system_prompt: str | None,
    resume_session_id: str | None,
    include_roles: list[str] | None,
    tier_preference: str | None,
    current_branch: str | None,
) -> None:
    """Apply execution/runtime optional fields to payload in-place."""
    if container_id:
        payload["container_id"] = container_id
    if max_turns > 1:
        payload["max_turns"] = max_turns
    if working_dir:
        payload["working_dir"] = working_dir
    if execute_tools:
        payload["execute_tools"] = True
    if trace_id:
        payload["trace_id"] = trace_id
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    if thinking_level:
        payload["thinking_level"] = thinking_level
    if system_prompt:
        payload["system_prompt"] = system_prompt
    if resume_session_id:
        payload["resume_session_id"] = resume_session_id
    if include_roles is not None:
        payload["include_roles"] = include_roles
    if tier_preference:
        payload["tier_preference"] = tier_preference
    if current_branch:
        payload["current_branch"] = current_branch


def build_completion_payload(  # noqa: PLR0913
    messages: list[dict[str, str] | MessageInput | ToolResultMessage],
    project_id: str,
    agent_slug: str | None = None, model: str | None = None,
    temperature: float = 1.0, session_id: str | None = None,
    purpose: str | None = None, external_id: str | None = None,
    enable_caching: bool = True, use_memory: bool = False,
    memory_group_id: str | None = None,
    routing_config: RoutingConfig | dict[str, Any] | None = None,
    tools: list[dict[str, Any] | ToolDefinition] | None = None,
    enable_programmatic_tools: bool = False,
    container_id: str | None = None, max_turns: int = 1,
    working_dir: str | None = None, execute_tools: bool = False,
    trace_id: str | None = None, timeout_seconds: float | None = None,
    thinking_level: str | None = None, system_prompt: str | None = None,
    resume_session_id: str | None = None,
    include_roles: list[str] | None = None,
    tier_preference: str | None = None, current_branch: str | None = None,
) -> dict[str, Any]:
    """Build completion request payload.

    Returns:
        Dict payload ready to send to API.
    """
    msg_dicts = _normalize_messages(messages)
    tool_dicts = _normalize_tools(tools)
    payload: dict[str, Any] = {
        "messages": msg_dicts, "temperature": temperature,
        "project_id": project_id, "enable_caching": enable_caching,
    }
    _apply_identity_fields(
        payload, agent_slug, model, session_id, purpose, external_id,
        use_memory, memory_group_id, routing_config, tool_dicts,
        enable_programmatic_tools,
    )
    _apply_execution_fields(
        payload, container_id, max_turns, working_dir, execute_tools,
        trace_id, timeout_seconds, thinking_level, system_prompt,
        resume_session_id, include_roles, tier_preference, current_branch,
    )
    return payload


def handle_completion_response(
    response: httpx.Response,
    client_instance: Any,  # BaseClientMixin instance
) -> CompletionResponse:
    """Handle completion response and update client state if needed.

    Args:
        response: HTTP response from API.
        client_instance: Client instance to update if disabled.

    Returns:
        Parsed CompletionResponse.

    Raises:
        ClientDisabledError: If client is disabled via kill switch.
        Other exceptions from handle_error.
    """
    if not response.is_success:
        try:
            handle_error(response)
        except ClientDisabledError as e:
            # Enter dormant mode
            client_instance._disabled = True
            client_instance._disabled_reason = e.reason
            raise

    return CompletionResponse.model_validate(response.json())
