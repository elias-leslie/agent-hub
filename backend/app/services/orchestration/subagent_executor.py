"""Subagent execution logic with telemetry and error handling."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from textwrap import shorten

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent_models import SubagentConfig, SubagentResult

logger = logging.getLogger(__name__)


def _truncate_text(content: str, remaining_chars: int) -> str:
    """Return a bounded one-line excerpt for focused child context."""
    if remaining_chars <= 0:
        return ""
    collapsed = " ".join(content.split())
    if not collapsed:
        return ""
    width = max(remaining_chars, 32)
    excerpt = shorten(collapsed, width=width, placeholder=" ...")
    return excerpt[:remaining_chars].rstrip()


def _shape_context_messages(
    context: list[Message],
    config: SubagentConfig,
) -> list[Message]:
    """Convert parent context into a single focused brief by default."""
    if config.context_mode == "none":
        return []
    if config.context_mode == "full":
        return list(context)

    max_messages = max(config.max_context_messages, 0)
    if max_messages == 0 or config.max_context_chars <= 0:
        return []

    candidate_messages = [message for message in context if message.role != "system"]
    if not candidate_messages:
        return []

    selected = candidate_messages[-max_messages:]
    omitted = len(candidate_messages) - len(selected)
    remaining_chars = config.max_context_chars
    lines = ["Selected parent context:"]

    for message in selected:
        prefix = f"- {message.role}: "
        remaining_for_line = remaining_chars - len(prefix) - 1
        excerpt = _truncate_text(message.content, remaining_for_line)
        if not excerpt:
            break
        lines.append(f"{prefix}{excerpt}")
        remaining_chars -= len(prefix) + len(excerpt) + 1
        if remaining_chars <= 0:
            break

    if omitted > 0 and remaining_chars > 24:
        lines.append(f"- ({omitted} older message(s) omitted)")

    if len(lines) == 1:
        return []
    return [Message(role="user", content="\n".join(lines))]


async def _log_subagent_cost(
    project_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Create a lightweight session and log costs for a subagent execution.

    Fire-and-forget: logs warning on failure, never raises.
    """
    try:
        from app.db import async_session
        from app.models import CostLog
        from app.models import Session as DBSession
        from app.services.project_budget import record_project_cost
        from app.services.token_counter import estimate_cost

        session_id = str(uuid.uuid4())
        cost = estimate_cost(input_tokens, output_tokens, model)

        async with async_session() as db:
            session = DBSession(
                id=session_id,
                project_id=project_id,
                provider=provider,
                model=model,
                status="completed",
                session_type="completion",
                request_source="orchestration",
                models_used=[model],
                providers_used=[provider],
            )
            db.add(session)

            cost_log = CostLog(
                session_id=session_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost.total_cost_usd,
            )
            db.add(cost_log)
            await db.commit()

        await record_project_cost(project_id, cost.total_cost_usd)
    except Exception:
        logger.warning("Failed to log subagent cost for project %s", project_id, exc_info=True)


def build_messages(
    task: str,
    config: SubagentConfig,
    context: list[Message] | None = None,
) -> list[Message]:
    """Build message list with isolated context."""
    messages: list[Message] = []

    if config.system_prompt:
        messages.append(Message(role="system", content=config.system_prompt))

    if context:
        messages.extend(_shape_context_messages(context, config))

    messages.append(Message(role="user", content=task))

    return messages


def _messages_to_dicts(messages: list[Message]) -> list[dict[str, object]]:
    return [{"role": m.role, "content": m.content} for m in messages]


async def _call_pipeline(
    messages: list[Message],
    model: str,
    provider: str,
    config: SubagentConfig,
):
    """Invoke complete_internal with optional timeout, in DB-less mode."""
    from app.api.complete.core import complete_internal

    coro = complete_internal(
        messages=_messages_to_dicts(messages),
        model=model,
        provider=provider,
        temperature=config.temperature,
        project_id=config.project_id or "",
        db=None,
        thinking_level=config.thinking_level,
        tools=config.tools,
    )
    if config.timeout_seconds is None:
        return await coro
    return await asyncio.wait_for(coro, timeout=config.timeout_seconds)


def _record_success(span, result, config) -> str | None:
    """Record completion attributes on span and return updated trace_id or None."""
    span.set_attribute("subagent.status", "completed")
    span.set_attribute("subagent.input_tokens", result.input_tokens)
    span.set_attribute("subagent.output_tokens", result.output_tokens)
    span.set_attribute("subagent.total_tokens", result.input_tokens + result.output_tokens)
    if result.thinking_tokens:
        span.set_attribute("subagent.thinking_tokens", result.thinking_tokens)
    span.set_status(Status(StatusCode.OK))

    span_ctx = span.get_span_context()
    if span_ctx.is_valid:
        return format(span_ctx.trace_id, "032x")
    return None


async def _maybe_log_cost(config: SubagentConfig, result) -> None:
    """Fire-and-forget cost logging when project tracking is enabled."""
    if not (config.project_id and result.input_tokens + result.output_tokens > 0):
        return
    try:
        await _log_subagent_cost(
            project_id=config.project_id,
            provider=result.provider,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
    except Exception:
        logger.warning("Subagent cost logging failed", exc_info=True)


def _make_result(
    subagent_id: str,
    config: SubagentConfig,
    model: str,
    started_at: datetime,
    *,
    status: str,
    content: str = "",
    provider: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    thinking_content: str | None = None,
    thinking_tokens: int | None = None,
    error: str | None = None,
    parent_id: str | None = None,
    trace_id: str | None = None,
) -> SubagentResult:
    return SubagentResult(
        subagent_id=subagent_id,
        name=config.name,
        content=content,
        status=status,
        provider=provider or config.provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        error=error,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        parent_id=parent_id,
        trace_id=trace_id,
    )


async def _handle_success(span, subagent_id, config, model, started_at,
                         result, effective_trace_id, parent_id) -> SubagentResult:
    """Record span attributes, log cost, and return a completed SubagentResult."""
    updated_trace_id = _record_success(span, result, config)
    if updated_trace_id:
        effective_trace_id = updated_trace_id
    await _maybe_log_cost(config, result)
    return _make_result(
        subagent_id, config, result.model, started_at,
        status="completed",
        content=result.content,
        provider=result.provider,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        thinking_content=result.thinking_content,
        thinking_tokens=result.thinking_tokens,
        parent_id=parent_id,
        trace_id=effective_trace_id,
    )


async def _execute_in_span(
    span, subagent_id, task, config, model,
    context, parent_id, effective_trace_id, started_at,
) -> SubagentResult:
    """Run the pipeline call inside an already-active span and return a result."""
    messages = build_messages(task, config, context)
    span.set_attribute("subagent.message_count", len(messages))

    try:
        result = await _call_pipeline(messages, model, config.provider, config)
        return await _handle_success(
            span, subagent_id, config, model, started_at,
            result, effective_trace_id, parent_id,
        )

    except TimeoutError:
        logger.warning(
            f"Subagent {config.name} ({subagent_id}) timed out "
            f"after {config.timeout_seconds}s"
        )
        span.set_attribute("subagent.status", "timeout")
        span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
        span.record_exception(TimeoutError(f"Timeout after {config.timeout_seconds}s"))
        return _make_result(
            subagent_id, config, model, started_at,
            status="timeout",
            error=f"Execution timed out after {config.timeout_seconds} seconds",
            parent_id=parent_id,
            trace_id=effective_trace_id,
        )

    except Exception as e:
        logger.error(f"Subagent {config.name} ({subagent_id}) error: {e}")
        span.set_attribute("subagent.status", "error")
        span.set_status(Status(StatusCode.ERROR, str(e)))
        span.record_exception(e)
        return _make_result(
            subagent_id, config, model, started_at,
            status="error",
            error=str(e),
            parent_id=parent_id,
            trace_id=effective_trace_id,
        )


async def execute_subagent(
    task: str,
    config: SubagentConfig,
    model: str,
    context: list[Message] | None = None,
    parent_id: str | None = None,
    trace_id: str | None = None,
) -> SubagentResult:
    """Execute a subagent with telemetry and error handling."""
    subagent_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(UTC)

    tracer = get_tracer("agent-hub.orchestration.subagent")
    effective_trace_id = trace_id or get_current_trace_id()

    with tracer.start_as_current_span(
        f"subagent.spawn.{config.name}",
        kind=SpanKind.INTERNAL,
        attributes={
            "subagent.id": subagent_id,
            "subagent.name": config.name,
            "subagent.provider": config.provider,
            "subagent.model": model,
            "subagent.parent_id": parent_id or "",
            "subagent.task_length": len(task),
            "subagent.current_depth": config.current_depth,
            "subagent.max_spawn_depth": config.max_spawn_depth,
            "subagent.context_mode": config.context_mode,
        },
    ) as span:
        if config.timeout_seconds is not None:
            span.set_attribute("subagent.timeout_seconds", config.timeout_seconds)
        span.set_attribute("subagent.context_messages_supplied", len(context or []))
        logger.info(
            f"Spawning subagent {config.name} ({subagent_id}) "
            f"provider={config.provider} parent={parent_id} trace={effective_trace_id}"
        )

        return await _execute_in_span(
            span, subagent_id, task, config, model,
            context, parent_id, effective_trace_id, started_at,
        )
