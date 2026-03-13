"""Token accounting for memory injection."""

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
    """Tracks rendered token usage across memory categories.

    Attributes:
        mandates_tokens: Tokens used by mandate content
        guardrails_tokens: Tokens used by guardrail content
        reference_tokens: Tokens used by reference content
        continuity_tokens: Tokens used by continuity context
        mandates_total: Total mandates available before filtering
        guardrails_total: Total guardrails available before filtering
        reference_total: Total reference items available before filtering
    """

    mandates_tokens: int = 0
    guardrails_tokens: int = 0
    reference_tokens: int = 0
    continuity_tokens: int = 0
    mandates_total: int = 0
    guardrails_total: int = 0
    reference_total: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens used across all categories."""
        return self.mandates_tokens + self.guardrails_tokens + self.reference_tokens + self.continuity_tokens

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary for JSON serialization."""
        return {
            "mandates_tokens": self.mandates_tokens,
            "guardrails_tokens": self.guardrails_tokens,
            "reference_tokens": self.reference_tokens,
            "continuity_tokens": self.continuity_tokens,
            "total_tokens": self.total_tokens,
        }
