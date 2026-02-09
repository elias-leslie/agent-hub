"""Types for maker-checker verification pattern."""

from dataclasses import dataclass

from .subagent import SubagentResult


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
