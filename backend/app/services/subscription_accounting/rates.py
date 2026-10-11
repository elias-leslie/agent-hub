"""Rate tables for subscription accounting: API-equivalent value and Codex credit draw.

API-equivalent value is tokens x list price (ccusage-style). It measures value received from a flat
subscription and allocates the flat fee across projects/agents. It is never spend.

Claude: USD per million tokens, platform.claude.com/docs/en/about-claude/pricing (verified 2026-10-11).
Claude Code here uses the 1-hour cache TTL, so cache writes without a TTL split price at the 1h rate.
Opus fast mode is 2x and stacks with the cache multipliers; US-only inference_geo adds 1.1x.

Codex: credits per million tokens (input / cached input / output), learn.chatgpt.com/docs/pricing.md.
At CREDIT_API_PARITY_USD per credit the rate card equals API list price, so one table serves both
API-equivalent value and credit draw. Fast mode is 2x, Ultrafast 6x.
"""

from __future__ import annotations

from dataclasses import dataclass

SUBSCRIPTION_PROVIDERS = frozenset({"claude", "codex"})

# $ per credit at which the Codex rate card equals API list price. Used only for API-equivalent value;
# what a credit is worth to the owner lives on credit_lots (grant = $0 cash, purchase = price paid).
CREDIT_API_PARITY_USD = 0.04


@dataclass(frozen=True)
class ClaudeRate:
    input: float
    write_5m: float
    write_1h: float
    read: float
    output: float


CLAUDE_RATES: dict[str, ClaudeRate] = {
    "claude-opus-5-5": ClaudeRate(4.00, 5.00, 8.00, 0.20, 20.00),
    "claude-sonnet-5-5": ClaudeRate(2.00, 2.50, 4.00, 0.10, 10.00),
    "claude-haiku-5-5": ClaudeRate(0.10, 0.125, 0.20, 0.01, 0.50),
    "claude-fable-5-1": ClaudeRate(10.00, 12.50, 20.00, 0.25, 50.00),
}
# Haiku 5.5 prompts over 100k tokens bill every token class at 5x.
CLAUDE_LONG_PROMPT: dict[str, tuple[int, float]] = {"claude-haiku-5-5": (100_000, 5.0)}
CLAUDE_SPEED_MULT = {"fast": 2.0}
CLAUDE_GEO_MULT = {"us": 1.1}

# Codex credits per million tokens: (input, cached input, output).
CODEX_CREDIT_RATES: dict[str, tuple[float, float, float]] = {
    "gpt-6.1-sol": (50.0, 2.5, 250.0),
    "gpt-6-sol": (50.0, 5.0, 250.0),
    "gpt-6-luna": (2.5, 0.25, 12.5),
    "gpt-6-astra": (250.0, 25.0, 1250.0),
    "gpt-daybreak-blue": (100.0, 10.0, 500.0),
    "gpt-5.6-sol": (100.0, 10.0, 500.0),
}
CODEX_SPEED_MULT = {"fast": 2.0, "priority": 2.0, "ultrafast": 6.0}


def _strip_provider(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def claude_rate(model: str) -> ClaudeRate | None:
    key = _strip_provider(model).lower()
    if key in CLAUDE_RATES:
        return CLAUDE_RATES[key]
    for name, rate in CLAUDE_RATES.items():  # dated ids such as claude-opus-5-5-20260922
        if key.startswith(name):
            return rate
    return None


def codex_rate(model: str) -> tuple[float, float, float] | None:
    key = _strip_provider(model).lower()
    if key in CODEX_CREDIT_RATES:
        return CODEX_CREDIT_RATES[key]
    for name, rate in CODEX_CREDIT_RATES.items():  # rolling aliases such as gpt-daybreak-blue-latest
        if key.startswith(name + "-") or key == name:
            return rate
    return None


def provider_for_model(model: str) -> str | None:
    """Subscription provider for a model id, or None when the model is metered/local."""
    lowered = model.lower()
    if lowered.startswith("codex/") or codex_rate(lowered) is not None:
        return "codex"
    if lowered.startswith("claude") or lowered.startswith("anthropic/claude"):
        return "claude"
    return None


def claude_api_equiv_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write_5m: int = 0,
    cache_write_1h: int = 0,
    speed: str | None = None,
    geo: str | None = None,
) -> float | None:
    rate = claude_rate(model)
    if rate is None:
        return None
    mult = CLAUDE_SPEED_MULT.get(speed or "", 1.0) * CLAUDE_GEO_MULT.get(geo or "", 1.0)
    long = CLAUDE_LONG_PROMPT.get(_strip_provider(model).lower())
    if long and input_tokens + cache_read + cache_write_5m + cache_write_1h > long[0]:
        mult *= long[1]
    usd = (
        input_tokens * rate.input
        + cache_write_5m * rate.write_5m
        + cache_write_1h * rate.write_1h
        + cache_read * rate.read
        + output_tokens * rate.output
    ) / 1e6
    return usd * mult


def codex_credits(
    model: str,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    speed: str | None = None,
) -> float | None:
    """Rate-card credits for one call. input_tokens is uncached input (cached is billed separately)."""
    rate = codex_rate(model)
    if rate is None:
        return None
    mult = CODEX_SPEED_MULT.get((speed or "").lower(), 1.0)
    return (input_tokens * rate[0] + cached_input_tokens * rate[1] + output_tokens * rate[2]) / 1e6 * mult


@dataclass(frozen=True)
class CallValue:
    """Accounting view of one Hub-routed call."""

    billing_mode: str  # metered | subscription | local
    api_equiv_usd: float | None
    credit_rate_credits: float | None  # Codex credits this call would draw outside included limits


def subscription_call_value(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> CallValue | None:
    """Value of a Hub-routed subscription call, or None when the model bills per token (metered).

    Token counts follow the provider adapters' Usage: input is uncached input; cache_read/cache_write are separate.
    """
    provider = provider_for_model(model)
    if provider == "codex":
        credits = codex_credits(model, input_tokens=input_tokens, cached_input_tokens=cache_read, output_tokens=output_tokens)
        return CallValue("subscription", None if credits is None else credits * CREDIT_API_PARITY_USD, credits)
    if provider == "claude":
        usd = claude_api_equiv_usd(
            model, input_tokens=input_tokens, output_tokens=output_tokens, cache_read=cache_read, cache_write_1h=cache_write
        )
        return CallValue("subscription", usd, None)
    return None
