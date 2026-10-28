"""Reasoning-level / max-token helpers for ``stream_simple`` paths.

Direct port of pi-mono ``packages/ai/src/providers/simple-options.ts``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .types import (
    Context,
    Model,
    SimpleStreamOptions,
    StreamOptions,
    TextContent,
    ThinkingBudgets,
    ThinkingContent,
    ThinkingLevel,
    ToolCall,
    UserMessage,
)


def _context_text(context: Context) -> str:
    """The text a request carries (system prompt, tool definitions, messages), for a token estimate.

    Images and audio are left out: providers price them by their own rules.
    """

    parts: list[str] = [context.system_prompt or ""]
    for tool in context.tools or []:
        parts += [tool.name, tool.description, json.dumps(tool.parameters, default=str)]
    for message in context.messages:
        if isinstance(message, UserMessage) and isinstance(message.content, str):
            parts.append(message.content)
            continue
        for block in message.content:
            if isinstance(block, TextContent):
                parts.append(block.text)
            elif isinstance(block, ThinkingContent):
                parts.append(block.thinking)
            elif isinstance(block, ToolCall):
                parts += [block.name, json.dumps(block.arguments, default=str)]
    return "\n".join(parts)


def output_limit(model: Model[Any], context: Context | None) -> int | None:
    """Default output limit for a request that names none: the catalog's ``max_tokens`` for the model, lowered to what
    is left of the context window after the prompt.

    Chat-completion style providers refuse a request whose prompt plus ``max_tokens`` exceeds the window, and some
    catalog rows allow a large output next to a modest window (for example 16k of 32k), so a long prompt would be
    rejected rather than answered. A prompt already over the window is not clamped: the provider's own overflow error
    is the honest outcome, not a request for a handful of tokens. ``None`` when the catalog row has no output limit.
    """

    if model.max_tokens <= 0:
        return None
    if context is None or model.context_window <= 0:
        return model.max_tokens
    text = _context_text(context)
    # A token is at least one character, so the character count bounds the prompt: tokenize only when it could matter.
    if model.context_window - len(text) >= model.max_tokens:
        return model.max_tokens
    from app.services.token_counter import count_tokens

    room = model.context_window - count_tokens(text)
    return min(model.max_tokens, room) if room > 0 else model.max_tokens


def build_base_options(
    model: Model[Any],
    options: SimpleStreamOptions | None = None,
    api_key: str | None = None,
    context: Context | None = None,
) -> StreamOptions:
    """Translate :class:`SimpleStreamOptions` into provider-neutral base options.

    Without an explicit ``max_tokens`` the limit is the catalog's, fitted to the context window (``output_limit``).
    """

    if options is None:
        options = SimpleStreamOptions()

    max_tokens = options.max_tokens if options.max_tokens is not None else output_limit(model, context)

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
    "output_limit",
]
