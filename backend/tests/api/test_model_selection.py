"""The public selector is advisory, capability-aware, and metadata-only."""
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routing import model_selection
from app.routing.model_selection import SelectionRequest, select_model


@pytest.mark.asyncio
async def test_advice_shadow_and_override_use_catalog_and_preflight() -> None:
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None):
        result = await select_model(SelectionRequest(task_type="visual_reasoning", mode="shadow", assigned_model="codex-gpt-6.1-sol"))
        assert result["model"] == "codex/gpt-6.1-terra"
        assert result["available"] and not result["apply"] and not result["automatic_eligible"]
        assert result["shadow_comparison"] == {"assigned_model": "codex/gpt-6.1-sol", "same_model": False}
        assert result["provenance"]["benchmark_evidence"] is None
        override = await select_model(SelectionRequest(task_type="coding", override_model="gpt-6.1-terra", override_effort="low"))
        assert override["model"] == "openai/gpt-6.1-terra"
        assert not override["available"] and "tool execution" in str(override["unavailable_reasons"])
        assert override["provenance"]["kind"] == "explicit_override"


@pytest.mark.asyncio
async def test_cooldown_and_inactive_cannot_be_selected() -> None:
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=RuntimeError("provider cooldown active")):
        result = await select_model(SelectionRequest(task_type="general"))
        assert not result["available"] and "cooldown" in str(result["unavailable_reasons"])
    missing = await select_model(SelectionRequest(task_type="general", override_model="codex/unknown", override_effort="low"))
    assert not missing["available"] and not missing["apply"]


@pytest.mark.asyncio
async def test_automatic_requires_current_exact_benchmark_qualification(monkeypatch) -> None:
    policy = deepcopy(model_selection._POLICY)
    policy["policies"]["general"]["qualification"] = {
        "kind": "task_benchmark", "source": "https://example.org/benchmark", "assessed_at": "2026-01-01",
        "valid_until": "9999-12-31", "model": "codex/gpt-6.1-sol", "effort": "medium",
    }
    monkeypatch.setattr(model_selection, "_POLICY", policy)
    with patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None):
        result = await select_model(SelectionRequest(task_type="general", mode="automatic"))
        assert result["automatic_eligible"] and result["apply"]
        override = await select_model(SelectionRequest(task_type="general", mode="automatic", override_model="codex/gpt-6.1-sol", override_effort="medium"))
        assert not override["apply"]
        policy["policies"]["general"]["qualification"]["valid_until"] = "2020-01-01"
        assert not (await select_model(SelectionRequest(task_type="general", mode="automatic")))["apply"]


@pytest.mark.asyncio
async def test_api_rejects_content_and_missing_shadow_baseline() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
        assert (await client.post("/api/models/select", json={"task_type": "coding", "content": "private task"})).status_code == 422
        assert (await client.post("/api/models/select", json={"task_type": "coding", "mode": "shadow"})).status_code == 422
        assert (await client.post("/api/models/select", json={"task_type": "general", "override_model": "codex/gpt-6.1-sol"})).status_code == 422


@pytest.mark.asyncio
async def test_api_reports_stale_catalog_and_never_applies_unqualified_route() -> None:
    from datetime import UTC, datetime
    from types import SimpleNamespace

    catalog = SimpleNamespace(catalog_health=SimpleNamespace(is_stale=True),
                              last_sync=datetime(2026, 10, 18, tzinfo=UTC), last_model_review=None)
    with (patch("app.api.models.list_models", new_callable=AsyncMock, return_value=catalog),
          patch.object(model_selection, "route_preflight_error", new_callable=AsyncMock, return_value=None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"}) as client:
            response = await client.post("/api/models/select", json={"task_type": "writing", "mode": "automatic"})
    assert response.status_code == 200
    result = response.json()
    assert result["catalog_health"]["is_stale"] is True
    assert result["available"] and not result["apply"]
    assert result["provenance"]["benchmark_evidence"] is None
    assert "not directly comparable" in result["cost_comparison"]
