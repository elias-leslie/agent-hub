"""Dashboard stats count model calls only and report outcomes truthfully."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.api import dashboard_stats, health_logic
from app.routing import availability, registry


def _result(*, one: Any = None, rows: list[Any] | None = None, scalar: Any = None) -> MagicMock:
    result = MagicMock()
    result.one.return_value = one
    result.all.return_value = rows or []
    result.scalar.return_value = scalar
    return result


def _sql(statement: Any) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _db(*results: MagicMock) -> AsyncMock:
    db = AsyncMock()
    db.execute.side_effect = list(results)
    return db


def _memory_row() -> SimpleNamespace:
    return SimpleNamespace(
        total=3,
        avg_latency=12.0,
        avg_tokens=900.0,
        total_mandates=2,
        total_guardrails=1,
        total_refs=4,
        total_ref_index=7,
        total_ref_cited=1,
    )


@pytest.mark.asyncio
async def test_stats_count_only_model_calls_and_keep_reference_counts_separate() -> None:
    today = datetime.now(UTC).date()
    db = _db(
        _result(one=SimpleNamespace(total=4, success_count=3, avg_latency=500.0, p50=400.0, p95=900.0)),
        _result(rows=[SimpleNamespace(day=today, requests=4, errors=1)]),
        _result(rows=[SimpleNamespace(model="codex/gpt-5.5", avg_latency=500.0, request_count=4)]),
        _result(one=_memory_row()),
        _result(scalar=1),
        _result(scalar=9),
        _result(one=SimpleNamespace(total_cost=0.25, total_tokens=1000)),
    )

    stats = await dashboard_stats.get_dashboard_stats(db=db, days=7)

    for call in db.execute.await_args_list[:3]:
        sql = _sql(call.args[0])
        assert "request_logs.endpoint = '/api/complete'" in sql
        assert "request_logs.method = 'POST'" in sql
    assert stats.requests.total_requests == 4
    assert stats.requests.success_rate == 75.0
    assert stats.requests.error_count == 1
    assert sum(day.requests for day in stats.requests_by_day) == stats.requests.total_requests
    assert stats.memory.total_references == 4
    assert stats.memory.total_reference_index_entries == 7
    assert not hasattr(stats, "truncations")
    assert "timeout_count" not in stats.requests.model_dump()


@pytest.mark.asyncio
async def test_no_model_calls_reports_null_rates_not_perfect_success() -> None:
    db = _db(
        _result(one=SimpleNamespace(total=0, success_count=None, avg_latency=None, p50=None, p95=None)),
        _result(rows=[]),
        _result(rows=[]),
        _result(one=_memory_row()),
        _result(scalar=0),
        _result(scalar=0),
        _result(one=SimpleNamespace(total_cost=0, total_tokens=0)),
    )

    stats = await dashboard_stats.get_dashboard_stats(db=db, days=3)

    assert stats.requests.total_requests == 0
    assert stats.requests.success_rate is None
    assert stats.requests.p50_latency_ms is None
    assert len(stats.requests_by_day) in (3, 4)
    assert all(day.requests == 0 for day in stats.requests_by_day)


@pytest.mark.asyncio
async def test_requests_by_day_zero_fills_the_window() -> None:
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    cutoff = now - timedelta(days=2)
    db = _db(_result(rows=[SimpleNamespace(day=date(2026, 10, 9), requests=5, errors=2)]))

    series = await dashboard_stats._requests_by_day(db, cutoff, now)

    assert [(d.date, d.requests, d.errors) for d in series] == [
        ("2026-10-08", 0, 0),
        ("2026-10-09", 5, 2),
        ("2026-10-10", 0, 0),
    ]


@pytest.fixture
def two_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "list_workload_providers", lambda: ["codex", "gemini"])

    async def reason(provider: str) -> str | None:
        return None

    monkeypatch.setattr(availability, "provider_unavailable_reason", reason)


@pytest.mark.asyncio
async def test_provider_status_includes_recent_completion_failures(two_providers) -> None:
    now = datetime.now(UTC)
    db = _db(
        _result(
            rows=[
                SimpleNamespace(
                    model="codex/gpt-5.5",
                    calls=10,
                    failures=2,
                    latency_total=5000,
                    latency_samples=10,
                    last_call=now,
                    last_success=now - timedelta(minutes=10),
                ),
                SimpleNamespace(
                    model="not-a-catalog-model",
                    calls=3,
                    failures=3,
                    latency_total=30,
                    latency_samples=3,
                    last_call=now,
                    last_success=None,
                ),
            ]
        ),
        _result(
            rows=[
                SimpleNamespace(model="codex/gpt-5.5", status_code=502, created_at=now),
                SimpleNamespace(model="codex/gpt-5.5", status_code=500, created_at=now - timedelta(hours=1)),
                SimpleNamespace(model="not-a-catalog-model", status_code=500, created_at=now),
            ]
        ),
    )

    statuses = {s.name: s for s in await health_logic.provider_statuses(db)}

    failure_sql = _sql(db.execute.await_args_list[1].args[0])
    assert "request_logs.status_code >= 500 OR request_logs.status_code = 429" in failure_sql
    assert "request_logs.endpoint = '/api/complete'" in failure_sql
    codex = statuses["codex"].health
    assert codex is not None
    assert codex.state == "degraded"
    assert codex.consecutive_failures == 1
    assert codex.availability == pytest.approx(0.8)
    assert codex.latency_ms == 500
    assert codex.last_error == "HTTP 502 from codex/gpt-5.5"
    assert statuses["gemini"].health is None


@pytest.mark.asyncio
async def test_status_drops_circuit_breaker_stub() -> None:
    assert not hasattr(health_logic, "_get_circuit_breaker_info")


class TestDashboardProviderHealthEndpoint:
    def test_provider_health_reports_routing_provider_readiness(self, api_client) -> None:
        from unittest.mock import patch

        async def reason(provider: str) -> str | None:
            return None if provider == "codex" else "no credential is stored for provider gemini"

        with (
            patch("app.routing.registry.list_workload_providers", return_value=["codex", "gemini"]),
            patch("app.routing.availability.provider_unavailable_reason", side_effect=reason),
            patch("app.api.health_logic.recent_completion_outcomes", AsyncMock(return_value={})),
        ):
            response = api_client.get("/api/dashboard/provider-health")

        assert response.status_code == 200
        assert response.json() == {
            "providers": [
                {
                    "provider": "codex",
                    "state": "ready",
                    "latency_ms": None,
                    "availability": None,
                    "consecutive_failures": 0,
                    "recent_calls": 0,
                    "recent_failures": 0,
                    "last_error": None,
                },
                {
                    "provider": "gemini",
                    "state": "unavailable",
                    "latency_ms": None,
                    "availability": None,
                    "consecutive_failures": 0,
                    "recent_calls": 0,
                    "recent_failures": 0,
                    "last_error": "no credential is stored for provider gemini",
                },
            ]
        }
