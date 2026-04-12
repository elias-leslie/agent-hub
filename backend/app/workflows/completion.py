"""Completion workflow.

Runs complete_internal() natively async with Hatchet streaming
replacing Redis pub/sub for progress events.
"""

from __future__ import annotations

import logging
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel, Field

from app.hatchet_app import hatchet
from app.models.field_lengths import EXTERNAL_ID_MAX_LENGTH
from app.services.completion_events import (
    CompletionEventType,
    CompletionProgressEvent,
    store_task_result,
)

logger = logging.getLogger(__name__)


class CompletionInput(BaseModel):
    task_id: str
    messages: list[dict[str, Any]]
    model: str
    provider: str
    temperature: float = 0.7
    project_id: str | None = None
    session_id: str = ""
    external_id: str | None = Field(default=None, max_length=EXTERNAL_ID_MAX_LENGTH)
    client_id: str | None = None
    request_source: str | None = None
    agent_slug: str | None = None
    memory_group_id: str | None = None
    enable_caching: bool = False
    cache_ttl: str | None = None
    thinking_level: str | None = None
    tools: list[dict[str, Any]] | None = None
    enable_programmatic_tools: bool = False
    container_id: str | None = None
    response_format: dict[str, Any] | None = None
    skip_cache: bool = False
    max_turns: int = 1
    execute_tools: bool = False
    working_dir: str | None = None
    trace_id: str | None = None
    task_type: str | None = None
    phase: str | None = None
    user_messages_for_db: list[dict[str, Any]] | None = Field(default=None)


class CompletionResult(BaseModel):
    task_id: str
    content: str = ""
    model: str = "unknown"
    provider: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    session_id: str = ""
    memory_uuids: list[str] = Field(default_factory=list)
    cited_uuids: list[str] = Field(default_factory=list)
    from_cache: bool = False
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[dict[str, Any]] = Field(default_factory=list)


def _result_to_dict(result: Any, task_id: str) -> dict[str, Any]:
    """Convert CompletionInternalResult to JSON-serializable dict."""
    return {
        "task_id": task_id,
        "content": result.content,
        "model": result.model,
        "provider": result.provider,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason,
        "session_id": result.session_id,
        "memory_uuids": result.memory_uuids,
        "cited_uuids": result.cited_uuids,
        "from_cache": result.from_cache,
        "thinking_content": result.thinking_content,
        "thinking_tokens": result.thinking_tokens,
        "turns": result.turns,
        "tool_calls_count": result.tool_calls_count,
        "status": result.status,
        "error": result.error,
        "container_id": result.container_id,
        "progress_log": [
            {
                "turn": p.turn,
                "status": p.status,
                "message": p.message,
                "topic": p.topic,
                "tool_calls": p.tool_calls or [],
                "tool_results": p.tool_results or [],
                "thinking": p.thinking,
            }
            for p in (result.progress_log or [])
        ],
    }


def _make_stream_event(
    task_id: str,
    session_id: str,
    event_type: CompletionEventType,
    data: dict[str, Any] | None = None,
) -> str:
    """Create a JSON string for streaming via Hatchet."""
    event = CompletionProgressEvent(
        task_id=task_id,
        session_id=session_id,
        event_type=event_type,
        data=data or {},
    )
    return event.to_json()


async def _wake_persona_on_autocode_failure(
    input: CompletionInput, error: str
) -> None:
    """Fire-and-forget wake for persona on autocode task failure."""
    from app.db import async_session
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_service import get_agent_service
    from app.workflows.persona_wake import dispatch_wake

    async with async_session() as db:
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, "persona")
        if not agent:
            return
        provider = get_provider_for_model(agent.primary_model_id)

    error_snippet = error[:2000]
    prompt = (
        f"Autocode task failed and needs triage.\n\n"
        f"Task ID: {input.task_id}\n"
        f"Project: {input.project_id or 'unknown'}\n"
        f"Agent: {input.agent_slug or 'unknown'}\n"
        f"Model: {input.model}\n\n"
        f"Error:\n{error_snippet}\n\n"
        f"Investigate the failure and decide next steps:\n"
        f"- Check `st context {input.task_id}` for full context\n"
        f"- If fixable: retry or dispatch a fix\n"
        f"- If systemic: log a bug and skip"
    )

    dispatch_wake(
        agent_slug="persona",
        model=agent.primary_model_id,
        provider=provider,
        temperature=agent.temperature,
        prompt=prompt,
        project_id=input.project_id or "agent-hub",
        event_type="autocode_failure",
        thinking_level=agent.thinking_level,
    )
    logger.info("Dispatched persona wake for autocode failure %s", input.task_id)


@hatchet.task(
    name="agentic-completion",
    retries=0,
    input_validator=CompletionInput,
)
async def completion_task(input: CompletionInput, ctx: Context) -> dict[str, Any]:
    from app.api.complete.core import AgentProgress, complete_internal
    from app.api.complete.schemas import MessageInput
    from app.db import async_session

    task_id = input.task_id
    session_id = input.session_id

    await ctx.aio_put_stream(
        _make_stream_event(task_id, session_id, CompletionEventType.STARTED)
    )

    try:
        user_messages_for_db: list[MessageInput] | None = None
        if input.user_messages_for_db:
            user_messages_for_db = [MessageInput(**m) for m in input.user_messages_for_db]

        async def progress_callback(progress: AgentProgress) -> None:
            event_type = CompletionEventType.PROGRESS
            if progress.status == "turn_start":
                event_type = CompletionEventType.TURN_START
            elif progress.status == "tool_use":
                event_type = CompletionEventType.TOOL_USE
            elif progress.status == "tool_result":
                event_type = CompletionEventType.TOOL_RESULT

            await ctx.aio_put_stream(
                _make_stream_event(task_id, session_id, event_type, {
                    "turn": progress.turn,
                    "status": progress.status,
                    "message": progress.message,
                    "topic": progress.topic,
                })
            )

        kwargs: dict[str, Any] = {
            "messages": input.messages,
            "model": input.model,
            "provider": input.provider,
            "temperature": input.temperature,
            "project_id": input.project_id,
            "session_id": session_id,
            "external_id": input.external_id,
            "client_id": input.client_id,
            "request_source": input.request_source,
            "agent_slug": input.agent_slug,
            "memory_group_id": input.memory_group_id,
            "enable_caching": input.enable_caching,
            "cache_ttl": input.cache_ttl,
            "thinking_level": input.thinking_level,
            "tools": input.tools,
            "enable_programmatic_tools": input.enable_programmatic_tools,
            "container_id": input.container_id,
            "response_format": input.response_format,
            "skip_cache": input.skip_cache,
            "max_turns": input.max_turns,
            "execute_tools": input.execute_tools,
            "working_dir": input.working_dir,
            "trace_id": input.trace_id,
            "task_type": input.task_type,
            "phase": input.phase,
        }

        async with async_session() as db:
            result = await complete_internal(
                db=db,
                user_messages_for_db=user_messages_for_db,
                progress_callback=progress_callback,
                use_memory=False,
                **kwargs,
            )

        result_dict = _result_to_dict(result, task_id)

        store_task_result(task_id, result_dict)

        await ctx.aio_put_stream(
            _make_stream_event(task_id, session_id, CompletionEventType.COMPLETED, {
                "turns": result_dict.get("turns", 1),
                "tool_calls_count": result_dict.get("tool_calls_count", 0),
            })
        )

        return result_dict

    except Exception as e:
        logger.exception("Agentic completion failed for task %s: %s", task_id, e)
        error_result: dict[str, Any] = {
            "task_id": task_id,
            "session_id": session_id,
            "status": "failed",
            "error": str(e),
        }
        store_task_result(task_id, error_result)

        await ctx.aio_put_stream(
            _make_stream_event(
                task_id, session_id, CompletionEventType.FAILED, {"error": str(e)}
            )
        )

        # Wake persona on autocode failure for immediate triage
        if input.task_type == "autocode":
            try:
                await _wake_persona_on_autocode_failure(input, str(e))
            except Exception:
                logger.debug(
                    "Failed to dispatch wake for autocode failure %s", task_id
                )

        raise
