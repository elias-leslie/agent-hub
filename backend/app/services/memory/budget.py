"""Token budget management for memory injection.

Provides functions to count tokens and track budget usage across
the three memory categories: mandates, guardrails, and reference.
"""

from dataclasses import dataclass, field


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

    def to_dict(self) -> dict:
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


def check_budget(
    current_usage: BudgetUsage,
    additional_tokens: int,
) -> tuple[bool, int]:
    """Check if additional tokens fit within budget.

    Args:
        current_usage: Current budget usage state
        additional_tokens: Number of tokens to potentially add

    Returns:
        Tuple of (can_add, tokens_that_fit):
        - can_add: True if any tokens can be added
        - tokens_that_fit: Number of tokens that fit in remaining budget
    """
    remaining = current_usage.remaining

    if remaining <= 0:
        return False, 0

    tokens_that_fit = min(additional_tokens, remaining)
    can_add = tokens_that_fit > 0

    return can_add, tokens_that_fit


@dataclass
class BudgetResult:
    """Result of budget-constrained content selection.

    Attributes:
        content: Content that fits within budget
        tokens_used: Tokens used by the content
        was_truncated: Whether content was truncated to fit
        hit_limit: Whether budget limit was reached
    """

    content: list = field(default_factory=list)
    tokens_used: int = 0
    was_truncated: bool = False
    hit_limit: bool = False


def select_within_budget(
    items: list[tuple[str, int]],  # List of (content, tokens) tuples
    remaining_budget: int,
) -> BudgetResult:
    """Select items that fit within remaining budget.

    Uses priority fill - items are added in order until budget exhausted.
    No truncation of individual items (quality over quantity).

    Args:
        items: List of (content, token_count) tuples in priority order
        remaining_budget: Tokens available in budget

    Returns:
        BudgetResult with selected content
    """
    selected = []
    tokens_used = 0
    hit_limit = False

    for content, token_count in items:
        if tokens_used + token_count <= remaining_budget:
            selected.append(content)
            tokens_used += token_count
        else:
            # Can't fit this item, budget exhausted
            hit_limit = True
            break

    return BudgetResult(
        content=selected,
        tokens_used=tokens_used,
        was_truncated=len(selected) < len(items),
        hit_limit=hit_limit,
    )
