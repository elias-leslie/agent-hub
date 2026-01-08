"""Maker-Checker verification pattern.

Uses two agents: one to generate output (maker) and another to verify (checker).
Common patterns:
- Code generation + code review
- Answer generation + fact checking
- Analysis + validation
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.adapters.base import Message
from app.services.telemetry import get_current_trace_id, get_tracer

from .subagent import SubagentConfig, SubagentManager, SubagentResult

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result from maker-checker verification."""

    maker_result: SubagentResult
    """Output from the maker agent."""

    checker_result: SubagentResult
    """Verification from the checker agent."""

    approved: bool
    """Whether the checker approved the maker's output."""

    issues: list[str]
    """Issues identified by the checker."""

    suggestions: list[str]
    """Improvement suggestions from the checker."""

    confidence: float
    """Checker's confidence in the verification (0.0-1.0)."""

    final_output: str
    """The final output to use (maker's if approved, or revised)."""

    iterations: int = 1
    """Number of maker-checker iterations."""


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

        # Enhance checker system prompt if not set
        if not checker_config.system_prompt:
            self._checker_config.system_prompt = self._default_checker_prompt()

    def _default_checker_prompt(self) -> str:
        """Default system prompt for the checker agent."""
        return """You are a verification agent. Your role is to:
1. Review the output provided by another agent
2. Identify any issues, errors, or problems
3. Provide an approval decision (APPROVED or NEEDS_REVISION)
4. List specific issues if not approved
5. Suggest improvements if applicable

Format your response as:
DECISION: [APPROVED or NEEDS_REVISION]
CONFIDENCE: [0.0-1.0]
ISSUES:
- [issue 1]
- [issue 2]
SUGGESTIONS:
- [suggestion 1]
- [suggestion 2]

Be thorough but fair. Only reject if there are genuine problems."""

    def _parse_checker_response(self, content: str) -> dict[str, Any]:
        """Parse checker response into structured data."""
        result: dict[str, Any] = {
            "approved": False,
            "confidence": 0.5,
            "issues": [],
            "suggestions": [],
        }

        lines = content.strip().split("\n")
        current_section: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("DECISION:"):
                decision = line.replace("DECISION:", "").strip().upper()
                result["approved"] = decision == "APPROVED"
            elif line.startswith("CONFIDENCE:"):
                try:
                    conf = float(line.replace("CONFIDENCE:", "").strip())
                    result["confidence"] = max(0.0, min(1.0, conf))
                except ValueError:
                    pass
            elif line.startswith("ISSUES:"):
                current_section = "issues"
            elif line.startswith("SUGGESTIONS:"):
                current_section = "suggestions"
            elif line.startswith("- ") and current_section:
                item = line[2:].strip()
                if item:
                    result[current_section].append(item)

        return result

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
        # Use provided trace_id or get from current context
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
            iterations = 0
            maker_result: SubagentResult | None = None
            checker_result: SubagentResult | None = None
            parsed: dict[str, Any] = {"approved": False, "confidence": 0.0, "issues": [], "suggestions": []}
            current_task = task

            while iterations < self._max_iterations:
            iterations += 1

            # Maker generates output
            maker_result = await self._subagent_manager.spawn(
                task=current_task,
                config=self._maker_config,
                context=context,
                trace_id=trace_id,
            )

            if maker_result.status != "completed":
                logger.warning(f"Maker failed with status {maker_result.status}")
                break

            # Checker verifies output
            checker_task = f"""Review the following output from another agent:

TASK: {task}

OUTPUT:
{maker_result.content}

Verify the output is correct, complete, and addresses the task."""

            checker_result = await self._subagent_manager.spawn(
                task=checker_task,
                config=self._checker_config,
                context=None,  # Checker gets fresh context
                trace_id=trace_id,
            )

            if checker_result.status != "completed":
                logger.warning(f"Checker failed with status {checker_result.status}")
                break

            # Parse checker response
            parsed = self._parse_checker_response(checker_result.content)

            if parsed["approved"]:
                logger.info(f"Maker output approved after {iterations} iteration(s)")
                break

            if iterations < self._max_iterations:
                # Prepare revision task with feedback
                feedback = "\n".join(parsed["issues"])
                suggestions = "\n".join(parsed["suggestions"])
                current_task = f"""Your previous attempt was not approved.

ORIGINAL TASK: {task}

YOUR PREVIOUS OUTPUT:
{maker_result.content}

ISSUES IDENTIFIED:
{feedback}

SUGGESTIONS:
{suggestions}

Please revise your output addressing the issues above."""
                logger.info(f"Iteration {iterations}: Maker revising based on feedback")

        # Ensure we have results
        if maker_result is None:
            raise RuntimeError("Maker failed to produce any output")
        if checker_result is None:
            # Create a default checker result
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


class CodeReviewPattern(MakerChecker):
    """Specialized maker-checker for code generation and review."""

    def __init__(
        self,
        maker_provider: Literal["claude", "gemini"] = "claude",
        checker_provider: Literal["claude", "gemini"] = "gemini",
        max_iterations: int = 2,
    ):
        """Initialize code review pattern.

        Uses different providers for maker and checker by default
        to get diverse perspectives.
        """
        maker_config = SubagentConfig(
            name="code_generator",
            provider=maker_provider,
            system_prompt="""You are an expert programmer. Generate clean, well-documented code.
Follow best practices and include error handling where appropriate.""",
            max_tokens=4096,
            temperature=0.7,
        )

        checker_config = SubagentConfig(
            name="code_reviewer",
            provider=checker_provider,
            system_prompt="""You are a senior code reviewer. Review code for:
1. Correctness - Does it solve the problem?
2. Security - Any vulnerabilities?
3. Performance - Any obvious inefficiencies?
4. Readability - Is it clear and maintainable?
5. Best practices - Does it follow conventions?

Format response as:
DECISION: [APPROVED or NEEDS_REVISION]
CONFIDENCE: [0.0-1.0]
ISSUES:
- [specific issues]
SUGGESTIONS:
- [specific improvements]""",
            max_tokens=2048,
            temperature=0.3,
        )

        super().__init__(
            maker_config=maker_config,
            checker_config=checker_config,
            max_iterations=max_iterations,
        )
