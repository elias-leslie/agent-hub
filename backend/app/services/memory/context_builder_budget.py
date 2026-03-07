"""Budget enforcement for progressive context."""

from __future__ import annotations

import logging

from .budget import BudgetUsage, count_tokens
from .service import MemorySearchResult

logger = logging.getLogger(__name__)


def apply_budget_enforcement(
    mandates: list[MemorySearchResult],
    guardrails: list[MemorySearchResult],
    references: list[MemorySearchResult],
    budget: BudgetUsage,
) -> tuple[list[MemorySearchResult], list[MemorySearchResult], list[MemorySearchResult]]:
    """Apply budget caps to mandates, guardrails, and references using 55/30/15 split.

    Args:
        mandates: List of mandate episodes
        guardrails: List of guardrail episodes
        budget: BudgetUsage object with total_budget set

    Returns:
        Tuple of (filtered_mandates, filtered_guardrails, filtered_references)
    """
    total_budget = budget.total_budget
    mandates_cap = int(total_budget * 0.55)
    guardrails_cap = int(total_budget * 0.30)
    references_cap = max(0, total_budget - mandates_cap - guardrails_cap)

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

    reference_tokens = 0
    filtered_references = []
    for r in references:
        tokens = count_tokens(r.content)
        if reference_tokens + tokens <= references_cap:
            filtered_references.append(r)
            reference_tokens += tokens
        else:
            logger.debug("References tier cap hit: %d/%d tokens", reference_tokens, references_cap)
            break

    logger.info(
        "Budget allocation: M=%d/%d G=%d/%d R=%d/%d",
        mandates_tokens,
        mandates_cap,
        guardrails_tokens,
        guardrails_cap,
        reference_tokens,
        references_cap,
    )

    budget.mandates_tokens = mandates_tokens
    budget.guardrails_tokens = guardrails_tokens
    budget.reference_tokens = reference_tokens

    return filtered_mandates, filtered_guardrails, filtered_references
