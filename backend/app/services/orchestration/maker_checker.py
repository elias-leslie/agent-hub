"""Maker-Checker verification pattern.

Uses two agents: one to generate output (maker) and another to verify (checker).
Common patterns:
- Code generation + code review
- Answer generation + fact checking
- Analysis + validation
"""

import logging
from typing import Any

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.services.llm_messages import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .maker_checker_parser import build_default_checker_prompt, parse_checker_response
from .maker_checker_types import VerificationResult
from .subagent import SubagentConfig, SubagentManager, SubagentResult

# Note: CodeReviewPattern is re-exported from __init__.py
__all__ = ["MakerChecker", "VerificationResult"]

logger = logging.getLogger(__name__)


class MakerChecker:
    """Implements maker-checker verification pattern.

    The maker generates output, the checker reviews it.
    Optionally iterates until approval or max iterations reached.
    """

    def __init__(
        self,
        maker_config: SubagentConfig,
        checker_config: SubagentConfig,
        max_iterations: int = 3,
    ):
        """Initialize maker-checker.

        Args:
            maker_config: Configuration for the maker agent.
            checker_config: Configuration for the checker agent.
            max_iterations: Maximum verification iterations.
        """
        self._maker_config = maker_config
        self._checker_config = checker_config
        self._max_iterations = max_iterations
        self._subagent_manager = SubagentManager()

        if not checker_config.system_prompt:
            self._checker_config.system_prompt = build_default_checker_prompt()

    async def verify(
        self,
        task: str,
        context: list[Message] | None = None,
        trace_id: str | None = None,
    ) -> VerificationResult:
        """Run maker-checker verification.

        Args:
            task: The task for the maker.
            context: Optional context messages.
            trace_id: OpenTelemetry trace ID.

        Returns:
            VerificationResult with maker output and checker verification.
        """
        effective_trace_id = trace_id or get_current_trace_id()
        tracer = get_tracer("agent-hub.orchestration.maker_checker")

        with tracer.start_as_current_span(
            "maker_checker.verify",
            kind=SpanKind.INTERNAL,
            attributes={
                "maker_checker.maker_name": self._maker_config.name,
                "maker_checker.checker_name": self._checker_config.name,
                "maker_checker.max_iterations": self._max_iterations,
                "maker_checker.task_length": len(task),
            },
        ) as span:
            result = await self._run_verification_loop(task, context, effective_trace_id)
            self._set_span_attrs(span, result)
            return result

    async def _run_verification_loop(
        self, task: str, context: list[Message] | None, trace_id: str | None
    ) -> VerificationResult:
        """Run the maker-checker verification loop."""
        iterations, current_task = 0, task
        maker_result: SubagentResult | None = None
        checker_result: SubagentResult | None = None
        parsed = {"approved": False, "confidence": 0.0, "issues": [], "suggestions": []}

        while iterations < self._max_iterations:
            iterations += 1
            maker_result = await self._run_maker(current_task, context, trace_id)
            if maker_result.status != "completed":
                logger.warning(f"Maker failed: {maker_result.status}")
                break

            checker_result = await self._run_checker(task, maker_result.content, trace_id)
            if checker_result.status != "completed":
                logger.warning(f"Checker failed: {checker_result.status}")
                break

            parsed = parse_checker_response(checker_result.content)
            if parsed["approved"]:
                logger.info(f"Approved after {iterations} iteration(s)")
                break

            if iterations < self._max_iterations:
                current_task = self._build_revision_task(task, maker_result.content, parsed)
                logger.info(f"Iteration {iterations}: revising")

        return self._build_result(maker_result, checker_result, parsed, iterations)

    async def _run_maker(
        self, task: str, context: list[Message] | None, trace_id: str | None
    ) -> SubagentResult:
        """Run the maker agent."""
        return await self._subagent_manager.spawn(
            task=task, config=self._maker_config, context=context, trace_id=trace_id
        )

    async def _run_checker(
        self, original_task: str, maker_output: str, trace_id: str | None
    ) -> SubagentResult:
        """Run the checker agent."""
        task = (
            f"Review the following output from another agent:\n\n"
            f"TASK: {original_task}\n\nOUTPUT:\n{maker_output}\n\n"
            f"Verify the output is correct, complete, and addresses the task."
        )
        return await self._subagent_manager.spawn(
            task=task, config=self._checker_config, context=None, trace_id=trace_id
        )

    def _build_revision_task(
        self, task: str, output: str, parsed: dict[str, Any]
    ) -> str:
        """Build a revision task with feedback."""
        return (
            f"Your previous attempt was not approved.\n\n"
            f"ORIGINAL TASK: {task}\n\n"
            f"YOUR PREVIOUS OUTPUT:\n{output}\n\n"
            f"ISSUES IDENTIFIED:\n{'\n'.join(parsed['issues'])}\n\n"
            f"SUGGESTIONS:\n{'\n'.join(parsed['suggestions'])}\n\n"
            f"Please revise your output addressing the issues above."
        )

    def _build_result(
        self,
        maker_result: SubagentResult | None,
        checker_result: SubagentResult | None,
        parsed: dict[str, Any],
        iterations: int,
    ) -> VerificationResult:
        """Build final verification result."""
        if maker_result is None:
            raise RuntimeError("Maker failed to produce any output")

        if checker_result is None:
            checker_result = SubagentResult(
                subagent_id="none",
                name=self._checker_config.name,
                content="Checker did not run",
                status="error",
                provider=self._checker_config.provider,
                model=self._checker_config.model or "unknown",
                input_tokens=0,
                output_tokens=0,
            )

        return VerificationResult(
            maker_result=maker_result,
            checker_result=checker_result,
            approved=parsed["approved"],
            issues=parsed["issues"],
            suggestions=parsed["suggestions"],
            confidence=parsed["confidence"],
            final_output=maker_result.content,
            iterations=iterations,
        )

    def _set_span_attrs(self, span: Any, result: VerificationResult) -> None:
        """Set span attributes and status."""
        span.set_attribute("maker_checker.iterations", result.iterations)
        span.set_attribute("maker_checker.approved", result.approved)
        span.set_attribute("maker_checker.confidence", result.confidence)
        span.set_attribute("maker_checker.issue_count", len(result.issues))
        status = Status(StatusCode.OK if result.approved else StatusCode.ERROR)
        span.set_status(status)
