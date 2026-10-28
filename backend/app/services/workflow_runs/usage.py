"""One honest usage shape for every workflow attempt, and the totals built from it.

Each executor reports tokens its own way; ``finish_usage`` maps them to the shared keys:

- tokens: ``input_tokens`` (uncached), ``cache_read_tokens``, ``cache_write_tokens``, ``output_tokens``,
  ``reasoning_tokens`` (inside output), ``total_tokens``;
- ``cost_usd`` (null when nothing could price the attempt), ``cost_basis`` and ``cost_source``;
- ``rate_limit_windows`` (fraction of each subscription window used), ``rate_limit_resets`` (unix seconds, when the
  provider said) and ``rate_limit_observed_at``.

``cost_basis`` says what the number is: ``metered`` is cash billed per token; ``subscription_equiv`` is the list-price
value of work a flat subscription covered (never spend); ``unknown`` is a number or a gap nothing could classify.
``cost_source`` says where it came from: ``provider_reported`` or ``catalog_estimate``. Unknown is not zero: totals
keep unpriced attempts apart and never sum them as 0. Which providers are subscriptions is data
(``executor_defaults.json`` ``usage``); prices come from the model catalog.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from typing import Any

logger = logging.getLogger(__name__)


@cache
def usage_settings() -> Mapping[str, Any]:
    """The ``usage`` block of ``executor_defaults.json`` (read once)."""

    from .executor_common import load_defaults

    return load_defaults()["usage"]


BASES = ("metered", "subscription_equiv", "unknown")
SOURCES = ("provider_reported", "catalog_estimate")
_TOKEN_KEYS = ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")

# Legacy attempts stored before the shared shape: Claude Code's list-price total, Agent Hub's per-turn sum.
_LEGACY_SUBSCRIPTION_KEY = "total_cost_usd"


def _positive(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) and value > 0 else None


def _price_per_token_estimate(model: str, counts: Mapping[str, int]) -> float | None:
    """List price from the catalog's own per-million prices; None when the entry has none (0 is not a price)."""

    from app.services.subscription_accounting.rates import catalog_list_usd

    return catalog_list_usd(
        model,
        input_tokens=counts["input_tokens"],
        output_tokens=counts["output_tokens"],
        cache_read=counts["cache_read_tokens"],
        cache_write=counts["cache_write_tokens"],
    )


def estimate_list_cost(model: str, counts: Mapping[str, int]) -> float | None:
    """List-price cost of ``counts`` on ``model`` from the catalog, or None when the catalog has no price.

    Subscription models price through the same rate card as Agent Hub's own cost rows (Claude list price, Codex
    credits at API parity); any other model through its per-million prices.
    """

    from app.services.subscription_accounting.rates import subscription_call_value

    value = subscription_call_value(
        model,
        input_tokens=counts["input_tokens"],
        output_tokens=counts["output_tokens"],
        cache_read=counts["cache_read_tokens"],
        cache_write=counts["cache_write_tokens"],
    )
    if value is not None:
        return value.api_equiv_usd
    return _price_per_token_estimate(model, counts)


def harness_basis(provider: str | None, settings: Mapping[str, Any]) -> str:
    """What a harness attempt's cost means: its login is a subscription for these providers, else unknown."""

    return "subscription_equiv" if provider in set(settings.get("subscription_providers", ())) else "unknown"


def agent_hub_basis(model: str, counts: Mapping[str, int]) -> str:
    """Agent Hub's own cost rows: subscription value for subscription providers (Claude, Codex, OpenCode Go), cash for the rest.

    It follows the model's provider, the same rule Pi and the other harnesses use, so the executor never changes it."""

    from app.services.subscription_accounting.rates import subscription_call_value

    value = subscription_call_value(model, input_tokens=counts["input_tokens"], output_tokens=counts["output_tokens"])
    return "metered" if value is None else "subscription_equiv"


def finish_usage(
    counts: Mapping[str, Any],
    *,
    basis: str,
    price_models: Sequence[str] = (),
    reported: Any = None,
    reported_source: str = "provider_reported",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The attempt's usage in the shared shape.

    ``counts`` is ``Usage.as_dict()``. ``reported`` is the cost the provider itself reported: it wins when it is a real
    amount (a reported 0 means the harness had no price, so it is estimated from the catalog instead, or left unknown).
    """

    out: dict[str, Any] = {**counts, **(extra or {})}
    token_counts = {key: int(counts.get(key) or 0) for key in _TOKEN_KEYS}
    cost = _positive(reported)
    source = reported_source if cost is not None else None
    if cost is None and sum(token_counts.values()) > 0:
        for model in price_models:
            try:
                cost = _positive(estimate_list_cost(model, token_counts))
            except Exception:  # a pricing gap must not fail an attempt that already ran
                logger.exception("workflow usage: could not price %s", model)
                cost = None
            if cost is not None:
                source = "catalog_estimate"
                break
    out["cost_usd"] = cost
    out["cost_basis"] = basis if basis in BASES else "unknown"
    out["cost_source"] = source
    return out


def window_name(minutes: Any, names: Mapping[str, str]) -> str | None:
    return names.get(str(minutes)) if isinstance(minutes, int) and not isinstance(minutes, bool) else None


def codex_windows(
    rate_limits: Mapping[str, Any], names: Mapping[str, str]
) -> tuple[dict[str, float], dict[str, int]]:
    """(fraction used, reset unix seconds) by window name from a Codex ``rate_limits`` block (primary/secondary)."""

    windows: dict[str, float] = {}
    resets: dict[str, int] = {}
    for key in ("primary", "secondary"):
        window = rate_limits.get(key)
        if not isinstance(window, Mapping):
            continue
        name = window_name(window.get("window_minutes"), names)
        used = window.get("used_percent")
        if name and isinstance(used, int | float) and not isinstance(used, bool):
            windows[name] = round(float(used) / 100.0, 6)
            if isinstance(window.get("resets_at"), int):
                resets[name] = window["resets_at"]
    return windows, resets


# --- reading stored usage ------------------------------------------------------------------------------


def tokens_of(usage: Mapping[str, Any]) -> int | None:
    """total_tokens when the executor reported it, else the sum of the parts it did report."""

    if isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    parts = [usage[k] for k in _TOKEN_KEYS if isinstance(usage.get(k), int)]
    return sum(parts) if parts else None


def cost_of(usage: Mapping[str, Any]) -> tuple[float | None, str, str | None]:
    """(cost, basis, source) of a stored attempt, including attempts stored before the shared shape."""

    basis = usage.get("cost_basis")
    value = usage.get("cost_usd")
    if basis in BASES:
        cost = float(value) if isinstance(value, int | float) else None
        return cost, str(basis), usage.get("cost_source")
    if isinstance(usage.get(_LEGACY_SUBSCRIPTION_KEY), int | float):  # Claude Code list price
        return float(usage[_LEGACY_SUBSCRIPTION_KEY]), "subscription_equiv", "provider_reported"
    if isinstance(value, int | float):  # an older Agent Hub sum, whose basis was never recorded
        return float(value), "unknown", None
    return None, "unknown", None


def usage_totals(usages: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Tokens and cost over attempts, cost split by basis.

    Unknown is not zero: tokens are null when no attempt reported them, a basis with no priced attempt has a null
    ``usd``, and attempts that used tokens but have no price are counted in ``unpriced_attempts``.
    """

    tokens: list[int] = []
    by_basis: dict[str, dict[str, Any]] = {
        basis: {"usd": None, "attempts": 0, "unpriced_attempts": 0} for basis in BASES
    }
    estimated = 0
    for usage in usages:
        count = tokens_of(usage)
        cost, basis, source = cost_of(usage)
        if count is not None:
            tokens.append(count)
        if cost is None and not count:
            continue  # nothing was used, so there is nothing to price
        row = by_basis[basis]
        row["attempts"] += 1
        if cost is None:
            row["unpriced_attempts"] += 1
            continue
        row["usd"] = (row["usd"] or 0.0) + cost
        estimated += 1 if source == "catalog_estimate" else 0
    return {
        "total_tokens": sum(tokens) if tokens else None,
        "cost": {
            "by_basis": by_basis,
            "unpriced_attempts": sum(row["unpriced_attempts"] for row in by_basis.values()),
            "estimated_attempts": estimated,
        },
    }


# --- cost_logs -----------------------------------------------------------------------------------------


async def record_attempt_cost(
    db: Any,
    *,
    session_id: str,
    model: str,
    executor: str | None,
    usage: Mapping[str, Any],
) -> bool:
    """Add the attempt's ``cost_logs`` row (not committed). Agent Hub attempts write their own, per turn.

    Follows the existing conventions: subscription calls are $0 marginal with the list-price value in
    ``api_equiv_usd``; metered calls carry cash. A harness whose own transcript the usage collector already counts
    (Claude Code, Codex) is marked, and the readers that add the collector's totals leave marked rows out.
    """

    from sqlalchemy import select

    from app.models import CostLog
    from app.models.session import NATIVE_COUNTED_NOTE

    settings = usage_settings()
    counts = {key: int(usage.get(key) or 0) for key in _TOKEN_KEYS}
    cost, basis, source = cost_of(usage)
    if executor in (None, "agent_hub", "faux") or not any(counts.values()):
        return False
    if await db.scalar(select(CostLog.id).where(CostLog.session_id == session_id).limit(1)) is not None:
        return False  # one row per attempt, however often the outcome is committed
    native = executor in set(settings.get("native_transcript_executors", ()))
    notes = [NATIVE_COUNTED_NOTE if native else f"workflow attempt via {executor}"]
    if cost is None or basis == "unknown":
        notes.append("cost unknown")
    elif source == "catalog_estimate":
        notes.append("catalog estimate")
    subscription = basis == "subscription_equiv"
    db.add(
        CostLog(
            session_id=session_id,
            model=model[:100],
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"],
            cost_usd=cost if basis == "metered" and cost is not None else 0.0,
            billing_mode="subscription" if subscription else "metered",
            api_equiv_usd=cost if subscription else None,
            cost_note="; ".join(notes)[:200],
        )
    )
    return True
