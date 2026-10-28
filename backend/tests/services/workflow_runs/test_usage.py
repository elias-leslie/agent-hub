"""Shared attempt usage: pricing, basis, mixed-basis totals and the cost_logs row."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.models.session import NATIVE_COUNTED_NOTE
from app.services.workflow_runs import usage as usage_module
from app.services.workflow_runs.usage import (
    codex_windows,
    cost_of,
    estimate_list_cost,
    finish_usage,
    harness_basis,
    record_attempt_cost,
    usage_totals,
)

SETTINGS = usage_module.usage_settings()
COUNTS = {"input_tokens": 1000, "cache_read_tokens": 0, "cache_write_tokens": 0, "output_tokens": 100, "total_tokens": 1100}


def priced(per_m_in: float, per_m_out: float) -> Any:
    return SimpleNamespace(
        id="x/deepseek-flash",
        provider="opencode-go",
        cost=SimpleNamespace(
            input_per_m=per_m_in, output_per_m=per_m_out, cache_read_per_million=None,
            cache_write_per_million=None, subscription_rates=None,
        ),
    )


def test_a_cost_the_provider_reported_wins_and_is_labelled_so() -> None:
    usage = finish_usage(COUNTS, basis="subscription_equiv", price_models=["m"], reported=0.0025)
    assert (usage["cost_usd"], usage["cost_basis"], usage["cost_source"]) == (0.0025, "subscription_equiv", "provider_reported")


def test_a_zero_report_is_not_a_price_so_the_catalog_estimates_or_the_cost_stays_unknown(monkeypatch) -> None:
    monkeypatch.setattr("app.constants.catalog.get_model_entry", lambda m: priced(0.15, 0.6) if m == "known" else None)
    estimated = finish_usage(COUNTS, basis="subscription_equiv", price_models=["unlisted", "known"], reported=0)
    assert estimated["cost_usd"] == pytest.approx((1000 * 0.15 + 100 * 0.6) / 1e6)
    assert estimated["cost_source"] == "catalog_estimate"
    unknown = finish_usage(COUNTS, basis="subscription_equiv", price_models=["unlisted"], reported=0)
    assert unknown["cost_usd"] is None and unknown["cost_source"] is None


def test_the_catalog_never_invents_a_price(monkeypatch) -> None:
    free = SimpleNamespace(
        cost=SimpleNamespace(input_per_m=0, output_per_m=0, cache_read_per_million=None, cache_write_per_million=None)
    )
    monkeypatch.setattr("app.constants.catalog.get_model_entry", lambda _m: free)
    assert estimate_list_cost("anything-unrated", COUNTS) is None


def test_basis_follows_the_subscription_provider_list() -> None:
    assert harness_basis("codex", SETTINGS) == harness_basis("opencode-go", SETTINGS) == "subscription_equiv"
    assert harness_basis("claude", SETTINGS) == "subscription_equiv"
    assert harness_basis("openai", SETTINGS) == harness_basis(None, SETTINGS) == "unknown"


def test_codex_windows_use_the_claude_names_and_a_fraction() -> None:
    limits = {
        "primary": {"used_percent": 40.0, "window_minutes": 300, "resets_at": 1793035965},
        "secondary": {"used_percent": 6.0, "window_minutes": 10080, "resets_at": 1793600626},
        "credits": {"balance": "1"},
    }
    windows, resets = codex_windows(limits, SETTINGS["window_names"])
    assert windows == {"five_hour": 0.4, "seven_day": 0.06}
    assert resets == {"five_hour": 1793035965, "seven_day": 1793600626}
    assert codex_windows({"primary": {"used_percent": 1, "window_minutes": 7}}, SETTINGS["window_names"]) == ({}, {})


def test_stored_attempts_from_before_the_shared_shape_still_read() -> None:
    assert cost_of({"total_cost_usd": 0.04}) == (0.04, "subscription_equiv", "provider_reported")
    assert cost_of({"cost_usd": 0.02}) == (0.02, "unknown", None)
    assert cost_of({"input_tokens": 3}) == (None, "unknown", None)


def attempt(cost: float | None, basis: str, tokens: int = 100, source: str | None = "provider_reported") -> dict[str, Any]:
    return {"total_tokens": tokens, "cost_usd": cost, "cost_basis": basis, "cost_source": source}


def test_totals_split_by_basis_and_never_add_one_basis_to_another() -> None:
    totals = usage_totals([attempt(0.5, "metered"), attempt(2.0, "subscription_equiv"), attempt(1.0, "subscription_equiv", source="catalog_estimate")])
    by = totals["cost"]["by_basis"]
    assert (by["metered"]["usd"], by["subscription_equiv"]["usd"]) == (0.5, 3.0)
    assert (by["metered"]["attempts"], by["subscription_equiv"]["attempts"]) == (1, 2)
    assert by["unknown"] == {"usd": None, "attempts": 0, "unpriced_attempts": 0}
    assert totals["total_tokens"] == 300 and totals["cost"]["estimated_attempts"] == 1


def test_unknown_cost_is_counted_apart_and_not_summed_as_zero() -> None:
    totals = usage_totals([attempt(None, "subscription_equiv"), attempt(None, "unknown", source=None), {}])
    by = totals["cost"]["by_basis"]
    assert by["subscription_equiv"] == {"usd": None, "attempts": 1, "unpriced_attempts": 1}
    assert by["unknown"] == {"usd": None, "attempts": 1, "unpriced_attempts": 1}
    assert totals["cost"]["unpriced_attempts"] == 2  # the empty attempt used nothing and is not counted
    mixed = usage_totals([attempt(None, "subscription_equiv"), attempt(1.5, "subscription_equiv")])["cost"]["by_basis"]["subscription_equiv"]
    assert mixed == {"usd": 1.5, "attempts": 2, "unpriced_attempts": 1}
    assert usage_totals([{}])["total_tokens"] is None


class FakeDb:
    def __init__(self, existing: bool = False) -> None:
        self.added: list[Any] = []
        self.existing = existing

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def scalar(self, _statement: Any) -> int | None:
        return 1 if self.existing or self.added else None


async def test_a_pi_attempt_writes_one_subscription_row_with_its_list_value() -> None:
    db = FakeDb()
    usage = attempt(0.0025, "subscription_equiv")
    usage.update(input_tokens=900, output_tokens=100, cache_read_tokens=0, cache_write_tokens=0)
    assert await record_attempt_cost(db, session_id="s1", model="opencode-go/deepseek", executor="pi", usage=usage)
    (row,) = db.added
    assert (row.billing_mode, row.cost_usd, row.api_equiv_usd) == ("subscription", 0.0, 0.0025)
    assert (row.input_tokens, row.output_tokens, row.session_id) == (900, 100, "s1")
    assert not row.cost_note.startswith(NATIVE_COUNTED_NOTE)
    # Committing the same outcome again adds nothing.
    assert not await record_attempt_cost(db, session_id="s1", model="m", executor="pi", usage=usage)
    assert len(db.added) == 1


async def test_native_harness_rows_are_marked_and_agent_hub_attempts_write_none() -> None:
    usage = attempt(1.0, "subscription_equiv")
    usage.update(input_tokens=5, output_tokens=5, cache_read_tokens=0, cache_write_tokens=0)
    db = FakeDb()
    await record_attempt_cost(db, session_id="s", model="m", executor="codex", usage=usage)
    assert db.added[0].cost_note.startswith(NATIVE_COUNTED_NOTE)
    for executor in ("agent_hub", "faux", None):
        assert not await record_attempt_cost(FakeDb(), session_id="s", model="m", executor=executor, usage=usage)
    assert not await record_attempt_cost(FakeDb(), session_id="s", model="m", executor="pi", usage={})


async def test_an_unpriced_attempt_keeps_its_tokens_without_inventing_value() -> None:
    db = FakeDb()
    usage = attempt(None, "unknown", source=None)
    usage.update(input_tokens=7, output_tokens=3, cache_read_tokens=0, cache_write_tokens=0)
    await record_attempt_cost(db, session_id="s", model="m", executor="pi", usage=usage)
    row = db.added[0]
    assert (row.api_equiv_usd, row.cost_usd, row.input_tokens) == (None, 0.0, 7) and "cost unknown" in row.cost_note
