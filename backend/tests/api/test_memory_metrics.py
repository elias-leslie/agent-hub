"""Tests for memory metrics endpoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import TEST_HEADERS


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Async test client with source headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_memory_metrics_returns_enriched_injection_summary(
    client: AsyncClient,
) -> None:
    """Metrics endpoint exposes the shared injection summary shape."""
    payload = {
        "total_injections": 4,
        "period_start": "2026-03-06T00:00:00+00:00",
        "period_end": "2026-03-07T00:00:00+00:00",
        "period_granularity": "hour",
        "by_variant": [],
        "by_period": [],
        "overall_success_rate": 0.5,
        "overall_citation_rate": 0.25,
        "outcomes": {
            "success_count": 2,
            "fail_count": 1,
            "unknown_count": 1,
            "known_count": 3,
            "coverage_rate": 0.75,
            "success_rate": 0.667,
        },
    }

    with patch(
        "app.api.memory_metrics.get_injection_metrics_summary",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        response = await client.get("/api/memory/metrics?lookback=1d&period=hour")

    assert response.status_code == 200
    data = response.json()
    assert data["period_granularity"] == "hour"
    assert data["outcomes"]["unknown_count"] == 1


@pytest.mark.asyncio
async def test_memory_metrics_forwards_filters_and_lookback(
    client: AsyncClient,
) -> None:
    """Metrics endpoint forwards parsed lookback and optional filters."""
    payload = {
        "total_injections": 0,
        "period_start": "2026-03-06T00:00:00+00:00",
        "period_end": "2026-03-06T01:00:00+00:00",
        "period_granularity": "hour",
        "by_variant": [],
        "by_period": [],
        "overall_success_rate": 0.0,
        "overall_citation_rate": 0.0,
        "outcomes": {
            "success_count": 0,
            "fail_count": 0,
            "unknown_count": 0,
            "known_count": 0,
            "coverage_rate": 0.0,
            "success_rate": 0.0,
        },
    }

    with patch(
        "app.api.memory_metrics.get_injection_metrics_summary",
        new_callable=AsyncMock,
        return_value=payload,
    ) as mock_summary:
        response = await client.get(
            "/api/memory/metrics"
            "?lookback=1h"
            "&period=hour"
            "&variant_filter=ENHANCED"
            "&project_id_filter=agent-hub"
        )

    assert response.status_code == 200
    mock_summary.assert_awaited_once()
    kwargs = mock_summary.await_args.kwargs
    assert mock_summary.await_args.args == (timedelta(hours=1),)
    assert kwargs["period"] == "hour"
    assert kwargs["variant_filter"] == "ENHANCED"
    assert kwargs["project_id_filter"] == "agent-hub"
