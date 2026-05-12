"""Reasoning-level / max-token helpers for ``stream_simple`` paths.

Direct port of pi-mono ``packages/ai/src/providers/simple-options.ts``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .types import (
    Model,
    SimpleStreamOptions,
    StreamOptions,
    ThinkingBudgets,
    ThinkingLevel,
)


def build_base_options(
    model: Model[Any],
    options: SimpleStreamOptions | None = None,
    api_key: str | None = None,
) -> StreamOptions:
    """Translate :class:`SimpleStreamOptions` into provider-neutral base options."""

    if options is None:
        options = SimpleStreamOptions()

    if options.max_tokens is not None:
        max_tokens = options.max_tokens
    elif model.max_tokens > 0:
        max_tokens = min(model.max_tokens, 32000)
    else:
        max_tokens = None

    resolved_key = api_key or options.api_key

    return StreamOptions(
        temperature=options.temperature,
        max_tokens=max_tokens,
        signal=options.signal,
        api_key=resolved_key,
        transport=options.transport,
        cache_retention=options.cache_retention,
        session_id=options.session_id,
        on_payload=options.on_payload,
        on_response=options.on_response,
        headers=options.headers,
        timeout_ms=options.timeout_ms,
        max_retries=options.max_retries,
        max_retry_delay_ms=options.max_retry_delay_ms,
        metadata=options.metadata,
    )


def clamp_reasoning(effort: ThinkingLevel | None) -> ThinkingLevel | None:
    """Collapse ``"xhigh"`` to ``"high"`` (most providers don't go beyond high)."""

    if effort == "xhigh":
        return "high"
    return effort


def adjust_max_tokens_for_thinking(
    base_max_tokens: int,
    model_max_tokens: int,
    reasoning_level: ThinkingLevel,
    custom_budgets: ThinkingBudgets | None = None,
) -> tuple[int, int]:
    """Return ``(max_tokens, thinking_budget)`` for token-based thinking providers."""

    default_budgets = ThinkingBudgets(minimal=1024, low=2048, medium=8192, high=16384)
    budgets = replace(
        default_budgets,
        minimal=(custom_budgets.minimal if custom_budgets and custom_budgets.minimal is not None else default_budgets.minimal),
        low=(custom_budgets.low if custom_budgets and custom_budgets.low is not None else default_budgets.low),
        medium=(custom_budgets.medium if custom_budgets and custom_budgets.medium is not None else default_budgets.medium),
        high=(custom_budgets.high if custom_budgets and custom_budgets.high is not None else default_budgets.high),
    )

    min_output_tokens = 1024
    level = clamp_reasoning(reasoning_level)
    if level is None or level == "xhigh":
        # clamp_reasoning never returns "xhigh"; level is None only if reasoning_level was None
        # which callers shouldn't do — fall back to medium.
        level = "medium"

    budget_value = getattr(budgets, level)
    assert budget_value is not None, f"missing thinking budget for level {level!r}"
    thinking_budget = int(budget_value)

    max_tokens = min(base_max_tokens + thinking_budget, model_max_tokens)
    if max_tokens <= thinking_budget:
        thinking_budget = max(0, max_tokens - min_output_tokens)

    return max_tokens, thinking_budget


__all__ = [
    "adjust_max_tokens_for_thinking",
    "build_base_options",
    "clamp_reasoning",
]
