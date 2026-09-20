"""Tests for the deterministic owner-side web benchmark."""

from __future__ import annotations

import asyncio
import json


def test_benchmark_exercises_direct_fetch_focus_and_size_contracts() -> None:
    from app.cli.web_benchmark import benchmark_web

    payload = json.loads(asyncio.run(benchmark_web(iterations=1, max_chars=800)))

    assert payload["benchmark"] == "st web deterministic fetch"
    assert payload["iterations"] == 1
    assert payload["max_chars"] == 800
    assert payload["case_count"] == 3
    assert payload["passed"] is True

    cases = {case["name"]: case for case in payload["cases"]}
    product = cases["product_unit_price_1"]
    assert product["fetch_backend"] == "direct"
    assert product["checks"] == {
        "backend_direct": True,
        "content_within_budget": True,
        "has_price": True,
        "has_quantity": True,
        "has_unit_price": True,
        "output_token_efficient": True,
    }
    assert cases["focus_budget_1"]["checks"] == {
        "content_within_budget": True,
        "drops_unrelated_tail": True,
        "focused": True,
        "has_target": True,
        "output_token_efficient": True,
    }
    assert cases["invalid_scheme_error"]["checks"] == {
        "mentions_http": True,
        "output_token_efficient": True,
        "reports_error": True,
    }


def test_benchmark_reports_semantic_failures(monkeypatch) -> None:
    from app.cli.web_benchmark import benchmark_web

    async def _fake_fetch_web_page(url: str, **kwargs: object) -> str:
        if url.startswith("file:"):
            return json.dumps({"error": "only supports http:// and https:// URLs"})
        return json.dumps({"content": "missing benchmark evidence", "fetch_backend": "direct"})

    monkeypatch.setattr("app.cli.web_benchmark.fetch_web_page", _fake_fetch_web_page)

    payload = json.loads(asyncio.run(benchmark_web(iterations=1, max_chars=800)))

    assert payload["passed"] is False
    assert payload["case_count"] == 3
    assert any(case["passed"] is False for case in payload["cases"])
