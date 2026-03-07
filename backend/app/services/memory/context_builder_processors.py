"""Post-processing logic for progressive context."""

from __future__ import annotations

import logging

from .budget import count_tokens
from .service import MemorySearchResult
from .settings import MemorySettingsDTO

logger = logging.getLogger(__name__)


def apply_count_limits(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    settings: MemorySettingsDTO,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Apply max_mandates and max_guardrails count limits.

    Returns:
        Tuple of (limited_mandates, limited_guardrails)
    """
    if settings.max_mandates > 0 and len(mandates) > settings.max_mandates:
        logger.info(
            "Applying mandate count limit: %d -> %d",
            len(mandates),
            settings.max_mandates,
        )
        mandates = mandates[: settings.max_mandates]

    if settings.max_guardrails > 0 and len(guardrails) > settings.max_guardrails:
        logger.info(
            "Applying guardrail count limit: %d -> %d",
            len(guardrails),
            settings.max_guardrails,
        )
        guardrails = guardrails[: settings.max_guardrails]

    return mandates, guardrails


def compute_token_counts(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
) -> tuple[int, int, int]:
    """Compute total tokens for mandates, guardrails, and references.

    Returns:
        Tuple of (mandates_tokens, guardrails_tokens, reference_tokens)
    """
    mandates_tokens = sum(count_tokens(m.content) for m in mandates)
    guardrails_tokens = sum(count_tokens(g.content) for g in guardrails)
    reference_tokens = sum(count_tokens(r.content) for r in references)
    return mandates_tokens, guardrails_tokens, reference_tokens
