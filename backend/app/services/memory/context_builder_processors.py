"""Post-processing logic for progressive context."""

from __future__ import annotations

from .budget import count_tokens
from .context_builder_tiers import get_rendered_content
from .service import MemorySearchResult


def compute_token_counts(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
) -> tuple[int, int, int]:
    """Compute total tokens for mandates, guardrails, and references.

    Returns:
        Tuple of (mandates_tokens, guardrails_tokens, reference_tokens)
    """
    mandates_tokens = sum(count_tokens(get_rendered_content(m)) for m in mandates)
    guardrails_tokens = sum(count_tokens(get_rendered_content(g)) for g in guardrails)
    reference_tokens = sum(count_tokens(get_rendered_content(r)) for r in references)
    return mandates_tokens, guardrails_tokens, reference_tokens
