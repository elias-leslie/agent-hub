"""Chain execution for sequential subagent tasks.

Executes a pipeline of subagent steps sequentially, passing each step's
output to the next via the ``{previous}`` placeholder in the task string.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.services.llm_messages import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent import SubagentConfig, SubagentManager, SubagentResult

logger = logging.getLogger(__name__)

__all__ = ["ChainExecutor", "ChainResult", "ChainStep"]


@dataclass
class ChainStep:
    """A step in a chain execution."""

    task: str
    """Task string. Use ``{previous}`` to inject the prior step's output."""

    config: SubagentConfig
    """Agent configuration for this step."""

    context: list[Message] | None = None
    """Optional additional context messages."""

    id: str | None = None
    """Optional step identifier."""


@dataclass
class ChainResult:
    """Result from chain execution."""

    results: list[SubagentResult]
    status: Literal["all_completed", "partial", "failed"]
    final_output: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    steps_completed: int = 0
    steps_total: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    trace_id: str | None = None


class ChainExecutor:
    """Execute subagent tasks sequentially with context passing.

    Each step receives the previous step's output via the ``{previous}``
    placeholder in its task string. If a step fails and ``stop_on_error``
    is True (default), the chain halts and returns partial results.
    """

    def __init__(self):
        self._subagent_manager = SubagentManager()

    async def execute(
        self,
        steps: list[ChainStep],
        overall_timeout: float | None = None,
        parent_id: str | None = None,
        trace_id: str | None = None,
        stop_on_error: bool = True,
    ) -> ChainResult:
        """Execute steps sequentially, passing each result as {previous} to the next."""
        effective_trace_id = trace_id or get_current_trace_id()

        if not steps:
            return ChainResult(
                results=[],
                status="all_completed",
                final_output="",
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                trace_id=effective_trace_id,
            )

        started_at = datetime.now(UTC)
        tracer = get_tracer("agent-hub.orchestration.chain")
        span_attrs: dict[str, Any] = {
            "chain.step_count": len(steps),
            "chain.timeout": overall_timeout or 0,
            "chain.stop_on_error": stop_on_error,
        }

        with tracer.start_as_current_span(
            "chain.execute", kind=SpanKind.INTERNAL, attributes=span_attrs
        ) as span:
            results: list[SubagentResult] = []
            previous_output = ""

            for i, step in enumerate(steps):
                # Substitute {previous} placeholder
                task = step.task.replace("{previous}", previous_output)

                logger.info(
                    f"Chain step {i + 1}/{len(steps)}: {step.config.name} "
                    f"trace={effective_trace_id}"
                )

                result = await self._subagent_manager.spawn(
                    task=task,
                    config=step.config,
                    context=step.context,
                    parent_id=parent_id,
                    trace_id=effective_trace_id,
                )
                results.append(result)

                if result.status != "completed":
                    logger.warning(
                        f"Chain step {i + 1} failed: {result.status} — {result.error}"
                    )
                    if stop_on_error:
                        break
                else:
                    previous_output = result.content

            completed_count = sum(1 for r in results if r.status == "completed")
            if completed_count == len(steps):
                status: Literal["all_completed", "partial", "failed"] = "all_completed"
            elif completed_count > 0:
                status = "partial"
            else:
                status = "failed"

            total_input = sum(r.input_tokens for r in results)
            total_output = sum(r.output_tokens for r in results)

            span.set_attribute("chain.status", status)
            span.set_attribute("chain.steps_completed", completed_count)
            span.set_attribute("chain.total_input_tokens", total_input)
            span.set_attribute("chain.total_output_tokens", total_output)
            span.set_status(
                Status(StatusCode.OK)
                if status == "all_completed"
                else Status(StatusCode.ERROR, f"Chain {status}")
            )

            return ChainResult(
                results=results,
                status=status,
                final_output=previous_output,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                steps_completed=completed_count,
                steps_total=len(steps),
                started_at=started_at,
                completed_at=datetime.now(UTC),
                trace_id=effective_trace_id,
            )
