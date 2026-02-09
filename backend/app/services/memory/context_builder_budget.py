"""Budget enforcement for progressive context."""

from __future__ import annotations

import logging

from .budget import BudgetUsage, count_tokens
from .service import MemorySearchResult

logger = logging.getLogger(__name__)


def apply_budget_enforcement(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    budget: BudgetUsage,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult]]:
    """Apply budget caps to mandates and guardrails using 60/40 split.

    Args:
        mandates: List of mandate episodes
        guardrails: List of guardrail episodes
        budget: BudgetUsage object with total_budget set

    Returns:
        Tuple of (filtered_mandates, filtered_guardrails)
    """
    total_budget = budget.total_budget
    mandates_cap = int(total_budget * 0.6)
    guardrails_cap = int(total_budget * 0.4)

    mandates_tokens = 0
    filtered_mandates = []
    for m in mandates:
        tokens = count_tokens(m.content)
        if mandates_tokens + tokens <= mandates_cap:
            filtered_mandates.append(m)
            mandates_tokens += tokens
        else:
            logger.debug("Mandates tier cap hit: %d/%d tokens", mandates_tokens, mandates_cap)
            break

    guardrails_tokens = 0
    filtered_guardrails = []
    for g in guardrails:
        tokens = count_tokens(g.content)
        if guardrails_tokens + tokens <= guardrails_cap:
            filtered_guardrails.append(g)
            guardrails_tokens += tokens
        else:
            logger.debug(
                "Guardrails tier cap hit: %d/%d tokens", guardrails_tokens, guardrails_cap
            )
            break

    logger.info(
        "Budget allocation: M=%d/%d G=%d/%d",
        mandates_tokens,
        mandates_cap,
        guardrails_tokens,
        guardrails_cap,
    )

    budget.mandates_tokens = mandates_tokens
    budget.guardrails_tokens = guardrails_tokens

    return filtered_mandates, filtered_guardrails
