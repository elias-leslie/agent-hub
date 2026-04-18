"""Tests for memory analytics dashboard endpoint."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.memory_dashboard import _store_summary_request_context
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
async def test_memory_analytics_returns_state_and_activity_sections(
    client: AsyncClient,
) -> None:
    """Dashboard endpoint returns the new explicit analytics sections."""
    payload = {
        "state": {
            "total_episodes": 10,
            "tier_distribution": [],
            "scope_distribution": [],
            "usage_totals": {
                "loaded": 100,
                "cited": 40,
                "helpful": 20,
                "harmful": 1,
            },
            "avg_utility_score": 0.4,
            "avg_lifecycle_score": 0.7,
            "lifecycle_by_tier": {"reference": 0.6},
            "top_memories": [],
        },
        "activity": {
            "lookback": "1d",
            "usage_totals": {
                "loaded": 12,
                "cited": 5,
                "helpful": 5,
                "harmful": 0,
                "success": 2,
            },
            "injection_metrics": {
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
            },
            "utilization": {
                "injection_sessions": 4,
                "citation_sessions": 2,
                "lookup_sessions": 3,
                "lookup_after_injection_sessions": 2,
                "memory_search_calls": 3,
                "memory_get_calls": 2,
                "assistant_message_count": 5,
                "assistant_messages_with_memory_citations": 2,
                "citation_session_rate": 0.5,
                "lookup_session_rate": 0.75,
                "expansion_session_rate": 0.5,
                "assistant_citation_rate": 0.4,
                "sessions_with_selected_references": 2,
                "sessions_with_cited_selected_references": 1,
                "selected_reference_count": 6,
                "selected_reference_cited_count": 3,
                "selected_reference_citation_rate": 0.5,
                "selected_reference_session_rate": 0.5,
                "memory_inject_event_count": 4,
                "memory_inject_events_with_debug": 4,
                "memory_debug_coverage_rate": 1.0,
            },
            "tier_changes": {"by_type": {}, "recent": [], "total": 0},
        },
    }

    with patch(
        "app.services.memory.analytics_service.get_memory_dashboard",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        response = await client.get("/api/memory/analytics?lookback=1d&sort_by=lifecycle_score")

    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"state", "activity"}
    assert data["activity"]["lookback"] == "1d"
    assert data["state"]["usage_totals"]["loaded"] == 100


@pytest.mark.asyncio
async def test_memory_analytics_forwards_lookback_and_sort(
    client: AsyncClient,
) -> None:
    """Endpoint forwards parsed lookback and top-memory sort to the service."""
    with patch(
        "app.services.memory.analytics_service.get_memory_dashboard",
        new_callable=AsyncMock,
        return_value={
            "state": {
                "total_episodes": 0,
                "tier_distribution": [],
                "scope_distribution": [],
                "usage_totals": {"loaded": 0, "cited": 0, "helpful": 0, "harmful": 0},
                "avg_utility_score": 0.0,
                "avg_lifecycle_score": 0.0,
                "lifecycle_by_tier": {},
                "top_memories": [],
            },
            "activity": {
                "lookback": "1h",
                "usage_totals": {
                    "loaded": 0,
                    "cited": 0,
                    "helpful": 0,
                    "harmful": 0,
                    "success": 0,
                },
                "injection_metrics": {
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
                },
                "utilization": {
                    "injection_sessions": 0,
                    "citation_sessions": 0,
                    "lookup_sessions": 0,
                    "lookup_after_injection_sessions": 0,
                    "memory_search_calls": 0,
                    "memory_get_calls": 0,
                    "assistant_message_count": 0,
                    "assistant_messages_with_memory_citations": 0,
                    "citation_session_rate": 0.0,
                    "lookup_session_rate": 0.0,
                    "expansion_session_rate": 0.0,
                    "assistant_citation_rate": 0.0,
                    "sessions_with_selected_references": 0,
                    "sessions_with_cited_selected_references": 0,
                    "selected_reference_count": 0,
                    "selected_reference_cited_count": 0,
                    "selected_reference_citation_rate": 0.0,
                    "selected_reference_session_rate": 0.0,
                    "memory_inject_event_count": 0,
                    "memory_inject_events_with_debug": 0,
                    "memory_debug_coverage_rate": 0.0,
                },
                "tier_changes": {"by_type": {}, "recent": [], "total": 0},
            },
        },
    ) as mock_dashboard:
        response = await client.get("/api/memory/analytics?lookback=1h&sort_by=lifecycle_score")

    assert response.status_code == 200
    mock_dashboard.assert_awaited_once()
    await_args = mock_dashboard.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["lookback_label"] == "1h"
    assert kwargs["lookback_delta"] == timedelta(hours=1)
    assert kwargs["top_memories_sort_by"] == "lifecycle_score"


@pytest.mark.asyncio
async def test_store_summary_request_context_persists_transcript_provenance() -> None:
    """Summary requests should retain transcript provenance for later reanalysis."""
    session = SimpleNamespace(
        provider_metadata={"cache": {"total_cache_read_tokens": 42}},
    )
    mock_result = SimpleNamespace(scalar_one_or_none=lambda: session)
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.memory_dashboard._get_session_factory", return_value=mock_factory):
        await _store_summary_request_context(
            "session-123",
            branch="main",
            transcript_path="/tmp/codex-session.jsonl",
            git_context="abc1234 feat: persist transcript context",
        )

    assert session.provider_metadata == {
        "cache": {"total_cache_read_tokens": 42},
        "summary_context": {
            "branch": "main",
            "transcript_path": "/tmp/codex-session.jsonl",
            "git_context": "abc1234 feat: persist transcript context",
        },
    }
    mock_db.commit.assert_awaited_once()
