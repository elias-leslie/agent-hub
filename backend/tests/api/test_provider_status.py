"""Status endpoints report routing providers by their pre-call readiness."""

from __future__ import annotations

import pytest

from app.api import dashboard_stats, health_logic
from app.routing import availability, registry


@pytest.fixture
def two_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "list_workload_providers", lambda: ["codex", "xai"])

    async def reason(provider: str) -> str | None:
        return None if provider == "codex" else "no credential is stored for provider xai"

    monkeypatch.setattr(availability, "provider_unavailable_reason", reason)


@pytest.mark.asyncio
async def test_status_lists_provider_ids_with_readiness(two_providers) -> None:
    statuses = await health_logic.provider_statuses()
    assert [(s.name, s.available, s.error, s.health) for s in statuses] == [
        ("codex", True, None, None),
        ("xai", False, "no credential is stored for provider xai", None),
    ]


@pytest.mark.asyncio
async def test_provider_health_reports_no_invented_metrics(two_providers) -> None:
    response = await dashboard_stats.get_provider_health(db=None)
    assert [(p.provider, p.state, p.latency_ms, p.availability) for p in response.providers] == [
        ("codex", "ready", None, None),
        ("xai", "unavailable", None, None),
    ]
