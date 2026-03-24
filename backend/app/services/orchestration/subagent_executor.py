"""Subagent execution logic with telemetry and error handling."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message, ProviderAdapter
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent_models import SubagentConfig, SubagentResult

logger = logging.getLogger(__name__)


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
    """Build message list with isolated context.

    Args:
        task: The task description.
        config: Subagent configuration.
        context: Optional context messages.

    Returns:
        List of messages with system prompt, context, and task.
    """
    messages: list[Message] = []

    # Add system prompt
    if config.system_prompt:
        messages.append(Message(role="system", content=config.system_prompt))

    # Add context messages if provided
    if context:
        messages.extend(context)

    # Add the task as user message
    messages.append(Message(role="user", content=task))

    return messages


async def execute_subagent(
    task: str,
    config: SubagentConfig,
    adapter: ProviderAdapter,
    model: str,
    context: list[Message] | None = None,
    parent_id: str | None = None,
    trace_id: str | None = None,
) -> SubagentResult:
    """Execute a subagent with telemetry and error handling.

    Args:
        task: The task description.
        config: Subagent configuration.
        adapter: Provider adapter to use.
        model: Model name to use.
        context: Optional context messages.
        parent_id: Parent subagent ID.
        trace_id: OpenTelemetry trace ID.

    Returns:
        SubagentResult with execution outcome.
    """
    subagent_id = str(uuid.uuid4())[:8]
    started_at = datetime.now(UTC)

    # Get tracer and create span
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
        },
    ) as span:
        if config.timeout_seconds is not None:
            span.set_attribute("subagent.timeout_seconds", config.timeout_seconds)
        logger.info(
            f"Spawning subagent {config.name} ({subagent_id}) "
            f"provider={config.provider} parent={parent_id} trace={effective_trace_id}"
        )

        # Build messages with isolated context
        messages = build_messages(task, config, context)

        try:
            if config.timeout_seconds is None:
                result = await adapter.complete(
                    messages=messages,
                    model=model,
                    temperature=config.temperature,
                    thinking_level=config.thinking_level,
                    tools=config.tools,
                )
            else:
                result = await asyncio.wait_for(
                    adapter.complete(
                        messages=messages,
                        model=model,
                        temperature=config.temperature,
                        thinking_level=config.thinking_level,
                        tools=config.tools,
                    ),
                    timeout=config.timeout_seconds,
                )

            # Record success in span
            span.set_attribute("subagent.status", "completed")
            span.set_attribute("subagent.input_tokens", result.input_tokens)
            span.set_attribute("subagent.output_tokens", result.output_tokens)
            span.set_attribute("subagent.total_tokens", result.input_tokens + result.output_tokens)
            if result.thinking_tokens:
                span.set_attribute("subagent.thinking_tokens", result.thinking_tokens)
            span.set_status(Status(StatusCode.OK))

            # Update effective_trace_id from current span context
            span_ctx = span.get_span_context()
            if span_ctx.is_valid:
                effective_trace_id = format(span_ctx.trace_id, "032x")

            # Log cost if project tracking is enabled (fire-and-forget)
            if config.project_id and result.input_tokens + result.output_tokens > 0:
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

            return SubagentResult(
                subagent_id=subagent_id,
                name=config.name,
                content=result.content,
                status="completed",
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                thinking_content=result.thinking_content,
                thinking_tokens=result.thinking_tokens,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                parent_id=parent_id,
                trace_id=effective_trace_id,
            )

        except TimeoutError:
            logger.warning(
                f"Subagent {config.name} ({subagent_id}) timed out "
                f"after {config.timeout_seconds}s"
            )
            span.set_attribute("subagent.status", "timeout")
            span.set_status(Status(StatusCode.ERROR, "Execution timed out"))
            span.record_exception(TimeoutError(f"Timeout after {config.timeout_seconds}s"))

            return SubagentResult(
                subagent_id=subagent_id,
                name=config.name,
                content="",
                status="timeout",
                provider=config.provider,
                model=model,
                input_tokens=0,
                output_tokens=0,
                error=f"Execution timed out after {config.timeout_seconds} seconds",
                started_at=started_at,
                completed_at=datetime.now(UTC),
                parent_id=parent_id,
                trace_id=effective_trace_id,
            )

        except Exception as e:
            logger.error(f"Subagent {config.name} ({subagent_id}) error: {e}")
            span.set_attribute("subagent.status", "error")
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)

            return SubagentResult(
                subagent_id=subagent_id,
                name=config.name,
                content="",
                status="error",
                provider=config.provider,
                model=model,
                input_tokens=0,
                output_tokens=0,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(UTC),
                parent_id=parent_id,
                trace_id=effective_trace_id,
            )
