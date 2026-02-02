"""Token budget management for memory injection.

Provides functions to count tokens and track budget usage across
the three memory categories: mandates, guardrails, and reference.
"""

from dataclasses import dataclass


def count_tokens(text: str) -> int:
    """Estimate token count for a piece of text.

    Uses simple length/4 estimate which is reasonably accurate for
    English text without requiring tokenizer dependencies.

    Args:
        text: Text to count tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0
    # Simple heuristic: ~4 characters per token on average
    return len(text) // 4


@dataclass
class BudgetUsage:
    """Tracks token usage across memory categories.

    Attributes:
        mandates_tokens: Tokens used by mandate content
        guardrails_tokens: Tokens used by guardrail content
        reference_tokens: Tokens used by reference content
        total_tokens: Total tokens used
        total_budget: Configured budget limit
        remaining: Tokens remaining in budget
        hit_limit: Whether budget limit was reached
        mandates_total: Total mandates available before budget cutoff
        guardrails_total: Total guardrails available before budget cutoff
        reference_total: Total reference items available before budget cutoff
    """

    mandates_tokens: int = 0
    guardrails_tokens: int = 0
    reference_tokens: int = 0
    total_budget: int = 2000
    # Total counts (before budget filtering)
    mandates_total: int = 0
    guardrails_total: int = 0
    reference_total: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all categories."""
        return self.mandates_tokens + self.guardrails_tokens + self.reference_tokens

    @property
    def remaining(self) -> int:
        """Tokens remaining in budget."""
        return max(0, self.total_budget - self.total_tokens)

    @property
    def hit_limit(self) -> bool:
        """Whether budget limit was reached."""
        return self.total_tokens >= self.total_budget

    def to_dict(self) -> dict[str, int | bool]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mandates_tokens": self.mandates_tokens,
            "guardrails_tokens": self.guardrails_tokens,
            "reference_tokens": self.reference_tokens,
            "total_tokens": self.total_tokens,
            "total_budget": self.total_budget,
            "remaining": self.remaining,
            "hit_limit": self.hit_limit,
        }
