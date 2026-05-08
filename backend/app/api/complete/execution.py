"""Completion execution logic for completion API."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from app.adapters.base import CompletionResult, Message
from app.adapters.registry import get_adapter
from app.adapters.thinking import get_thinking_config
from app.api.complete.helpers import should_enable_thinking
from app.api.complete.schemas import (
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    ThinkingInfo,
    UsageInfo,
)
from app.services.agent_routing import complete_with_fallback
from app.services.health_prober import record_provider_failure, record_provider_success

if TYPE_CHECKING:

    from app.api.complete.schemas import CompletionRequest
    from app.services.agent_routing import ResolvedAgent

logger = logging.getLogger(__name__)


def prepare_tools(request: CompletionRequest) -> list[dict[str, Any]] | None:
    """Convert tools from request to API format.

    Args:
        request: Completion request

    Returns:
        List of tool dicts or None if no tools
    """
    if not request.tools:
        return None

    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
            **(
                {"allowed_callers": t.allowed_callers}
                if t.allowed_callers != ["direct"]
                else {}
            ),
        }
        for t in request.tools
    ]


def prepare_response_format(request: CompletionRequest) -> dict[str, Any] | None:
    """Build response_format dict from request.

    Args:
        request: Completion request

    Returns:
        Response format dict or None
    """
    if not request.response_format:
        return None

    return {
        "type": request.response_format.type,
        "schema": request.response_format.schema_,
    }


def get_thinking_level(
    request: CompletionRequest,
    all_messages: list[Message],
    resolved_agent: ResolvedAgent | None = None,
) -> str | None:
    """Get thinking level for request.

    Priority: request.thinking_level > agent DB default > auto_thinking.

    Args:
        request: Completion request
        all_messages: All messages
        resolved_agent: Resolved agent (optional, provides DB default)

    Returns:
        Thinking level or None
    """
    thinking_level = request.thinking_level
    # Fall back to agent's DB-configured thinking_level
    if not thinking_level and resolved_agent and resolved_agent.agent.thinking_level:
        thinking_level = resolved_agent.agent.thinking_level
    if request.auto_thinking and not thinking_level and should_enable_thinking(all_messages):
        thinking_level = "medium"
    return thinking_level


async def execute_with_fallback(
    messages_for_adapter: list[Message],
    resolved_agent: ResolvedAgent,
    tools_api: list[dict[str, Any]] | None,
    thinking_level: str | None = None,
    resolved_model: str | None = None,
    prompt_cache_key: str | None = None,
) -> tuple[CompletionResult, str, bool]:
    """Execute completion with fallback chain.

    Args:
        messages_for_adapter: Messages for adapter
        resolved_agent: Resolved agent
        tools_api: Tools in API format
        thinking_level: Thinking level (from request or agent DB)
        resolved_model: Model override (e.g. from @mention). If different from
            agent's primary model, used as the primary for the fallback chain.

    Returns:
        Tuple of (result, model_used, fallback_used)
    """
    primary_override = None
    if resolved_model and resolved_model != resolved_agent.model:
        primary_override = resolved_model
    requested_model = primary_override or resolved_agent.model

    fallback_result = await complete_with_fallback(
        messages=messages_for_adapter,
        agent=resolved_agent.agent,
        temperature=resolved_agent.agent.temperature,
        tools=tools_api,
        thinking_level=thinking_level,
        primary_model_override=primary_override,
        prompt_cache_key=prompt_cache_key,
    )
    fallback_used = fallback_result.used_fallback and fallback_result.model_used != requested_model
    if fallback_used and fallback_result.fallback_reason:
        fallback_result.result.fallback_reason = fallback_result.fallback_reason
    return (
        fallback_result.result,
        fallback_result.model_used,
        fallback_used,
    )


async def execute_without_db(
    messages_for_adapter: list[Message],
    resolved_model: str,
    provider: str,
    request: CompletionRequest,
    thinking_level: str | None,
    tools_api: list[dict[str, Any]] | None,
    response_format_dict: dict[str, Any] | None,
    session_id: str | None = None,
) -> tuple[CompletionResult, str]:
    """Execute completion without database.

    Args:
        messages_for_adapter: Messages for adapter
        resolved_model: Resolved model
        provider: Provider name
        request: Completion request
        thinking_level: Thinking level
        tools_api: Tools in API format
        response_format_dict: Response format dict

    Returns:
        Tuple of (result, model_used)
    """
    from app.core.debug import debug, debug_async_timer

    adapter = get_adapter(provider)
    extra_kwargs: dict[str, Any] = {
        "enable_caching": request.enable_caching,
        "cache_ttl": request.cache_ttl,
        "tools": tools_api,
        "enable_programmatic_tools": request.enable_programmatic_tools,
        "container_id": request.container_id,
        "response_format": response_format_dict,
    }
    if session_id:
        extra_kwargs["prompt_cache_key"] = session_id
    if thinking_level:
        thinking_config = get_thinking_config(resolved_model, thinking_level, provider)
        if thinking_config:
            extra_kwargs.update(thinking_config)
        elif provider not in {
            "cloudflare", "codex", "deepseek", "local", "minimax",
            "moonshot", "nvidia", "openai", "openrouter", "xai", "zhipu",
        }:
            extra_kwargs["thinking_level"] = thinking_level

    debug(f"LLM request: model={resolved_model}, messages={len(messages_for_adapter)}")
    async with debug_async_timer(f"adapter.complete ({resolved_model})"):
        start = time.monotonic()
        try:
            result = await adapter.complete(
                messages=messages_for_adapter,
                model=resolved_model,
                max_tokens=None,
                temperature=request.temperature,
                **extra_kwargs,
            )
        except Exception as exc:
            record_provider_failure(provider, str(exc), (time.monotonic() - start) * 1000)
            raise
        record_provider_success(provider, (time.monotonic() - start) * 1000)
    debug(f"LLM response: tokens={result.input_tokens}+{result.output_tokens}")

    return result, resolved_model


def build_agentic_response(
    internal_result: Any,
    context_usage_info: ContextUsageInfo | None,
    thinking_level: str | None,
    agent_used: str | None,
    fallback_used: bool,
    trace_id: str | None,
) -> CompletionResponse:
    """Build agentic response from internal result.

    Args:
        internal_result: Result from complete_internal
        context_usage_info: Context usage info
        thinking_level: Thinking level used
        agent_used: Agent slug used
        fallback_used: Whether fallback was used
        trace_id: Trace ID

    Returns:
        CompletionResponse
    """
    from app.api.orchestration_models import AgentProgressInfo

    return CompletionResponse(
        content=internal_result.content,
        model=internal_result.model,
        provider=internal_result.provider,
        usage=UsageInfo(
            input_tokens=internal_result.input_tokens,
            output_tokens=internal_result.output_tokens,
            total_tokens=internal_result.input_tokens + internal_result.output_tokens,
            cache=None,
        ),
        context_usage=context_usage_info,
        output_usage=None,
        session_id=internal_result.session_id,
        finish_reason=internal_result.finish_reason
        if internal_result.status == "success"
        else internal_result.status,
        from_cache=internal_result.from_cache,
        thinking=ThinkingInfo(
            content=internal_result.thinking_content or "",
            tokens=internal_result.thinking_tokens,
            level_used=thinking_level,
        )
        if internal_result.thinking_tokens
        else None,
        tool_calls=None,
        container=ContainerInfo(
            id=internal_result.container_id or "",
            expires_at="",
        )
        if internal_result.container_id
        else None,
        memory_facts_injected=len(internal_result.memory_uuids),
        memory_uuids=",".join(internal_result.memory_uuids)
        if internal_result.memory_uuids
        else None,
        agent_used=agent_used,
        model_used=internal_result.model,
        fallback_used=fallback_used,
        turns=internal_result.turns,
        tool_calls_count=internal_result.tool_calls_count,
        progress_log=[
            AgentProgressInfo(
                turn=p.turn,
                status=p.status,
                message=p.message,
                topic=p.topic,
                tool_calls=p.tool_calls or [],
                tool_results=p.tool_results or [],
                thinking=p.thinking,
            )
            for p in internal_result.progress_log
        ]
        if internal_result.progress_log
        else None,
        error_summary=internal_result.error_summary,
        trace_id=trace_id,
        cited_uuids=internal_result.cited_uuids,
    )
