"""Subscription accounting: API-equivalent value and Codex credit draw.

API-equivalent value is tokens x list price (ccusage-style). It measures value received from a flat
subscription and allocates the flat fee across projects/agents. It is never spend.

Per-model prices come from the model catalog (DB models table), never from code:
Claude list prices are the row's input/output/cache read/cache write (5-minute) costs, and a
long-prompt multiplier sits in subscription_rates["long_prompt"]. Codex credits per million tokens
(input / cached input / output) sit in subscription_rates["credits_per_m"].

Pricing rules stay here. Claude Code uses the 1-hour cache TTL, so cache writes without a TTL split
price at the 1h rate, which is 2x base input. Opus fast mode is 2x and stacks with the cache
multipliers; US-only inference_geo adds 1.1x. At CREDIT_API_PARITY_USD per credit the Codex rate
card equals API list price, so one table serves both value and credit draw. Fast mode is 2x,
Ultrafast 6x.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants.catalog import INACTIVE_MODEL_CATALOG_BY_ID, MODEL_CATALOG_BY_ID, ModelEntry

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


# Anthropic prices a 1-hour cache write at 2x base input for every model.
CLAUDE_CACHE_1H_INPUT_MULT = 2.0
CLAUDE_SPEED_MULT = {"fast": 2.0}
CLAUDE_GEO_MULT = {"us": 1.1}

CODEX_SPEED_MULT = {"fast": 2.0, "priority": 2.0, "ultrafast": 6.0}


def _strip_provider(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def _catalog_match(model: str, provider: str, *, has: str | None = None) -> ModelEntry | None:
    """Longest catalog entry of a provider whose bare id is the model or a prefix of it.

    Covers dated ids (claude-opus-5-5-20260922) and rolling suffixes (-latest). With
    ``has``, only entries carrying that subscription_rates key qualify.
    """
    key = _strip_provider(model).lower()
    best: tuple[int, ModelEntry] | None = None
    for entry in (*MODEL_CATALOG_BY_ID.values(), *INACTIVE_MODEL_CATALOG_BY_ID.values()):
        if entry.provider != provider:
            continue
        if has is not None and has not in (entry.cost.subscription_rates or {}):
            continue
        bare = _strip_provider(entry.id).lower()
        for name in {bare, bare.removesuffix("-latest")}:
            if (key == name or key.startswith(name + "-")) and (best is None or len(name) > best[0]):
                best = (len(name), entry)
    return best[1] if best else None


def claude_rate(model: str) -> ClaudeRate | None:
    entry = _catalog_match(model, "claude")
    if entry is None or entry.cost.cache_read_per_million is None or entry.cost.cache_write_per_million is None:
        return None
    cost = entry.cost
    return ClaudeRate(
        input=cost.input_per_m,
        write_5m=cost.cache_write_per_million,
        write_1h=cost.input_per_m * CLAUDE_CACHE_1H_INPUT_MULT,
        read=cost.cache_read_per_million,
        output=cost.output_per_m,
    )


def _claude_long_prompt(model: str) -> tuple[int, float] | None:
    entry = _catalog_match(model, "claude")
    rule = (entry.cost.subscription_rates or {}).get("long_prompt") if entry else None
    return (int(rule["over_tokens"]), float(rule["multiplier"])) if rule else None


def codex_rate(model: str) -> tuple[float, float, float] | None:
    entry = _catalog_match(model, "codex", has="credits_per_m")
    if entry is None:
        return None
    card = (entry.cost.subscription_rates or {})["credits_per_m"]
    return float(card["input"]), float(card["cached_input"]), float(card["output"])


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
    long = _claude_long_prompt(model)
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


def catalog_list_usd(
    model: str, *, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0
) -> float | None:
    """List price of a call from the catalog's own per-million prices; None when the entry has none (0 is not a price).

    Token counts follow the provider adapters' Usage: input is uncached input; cache_read/cache_write are separate.
    """
    from app.constants.catalog import get_model_entry

    entry = get_model_entry(model)
    price = entry.cost if entry is not None else None
    if price is None or not (price.input_per_m or price.output_per_m):
        return None
    return (
        input_tokens * price.input_per_m
        + output_tokens * price.output_per_m
        + cache_read * (price.cache_read_per_million or 0.0)
        + cache_write * (price.cache_write_per_million or 0.0)
    ) / 1e6


def is_flat_subscription_provider(model: str) -> bool:
    """Whether the model's catalog provider is a flat subscription (data: ``executor_defaults.json`` ``usage``)."""
    from app.routing.registry import get_provider_for_model
    from app.services.workflow_runs.usage import usage_settings

    return get_provider_for_model(model) in set(usage_settings().get("subscription_providers", ()))


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

    Claude and Codex price from their rate cards; any other provider listed as a subscription in the workflow usage
    settings prices from the catalog list price. The provider decides, never the executor that ran the call.

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
    if is_flat_subscription_provider(model):
        # Any other flat subscription (OpenCode Go): $0 marginal, the value is the catalog list price.
        usd = catalog_list_usd(
            model, input_tokens=input_tokens, output_tokens=output_tokens, cache_read=cache_read, cache_write=cache_write
        )
        return CallValue("subscription", usd, None)
    return None
