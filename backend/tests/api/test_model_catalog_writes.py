"""Catalog writes go through the models API (the DB is the only catalog)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app
from app.models.model_catalog import ModelAlias, ModelCatalogEntry

_HEADERS = {"X-Agent-Hub-Internal": "agent-hub-internal-v1"}


async def _put(path: str, body: dict, db: AsyncMock):
    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with (
            patch("app.services.model_catalog_service.refresh_runtime_model_catalog", new_callable=AsyncMock),
            patch("app.api.models.require_service_client", new_callable=AsyncMock, return_value={"status": "active"}),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=_HEADERS) as client:
                return await client.put(path, json=body)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_repricing_an_existing_model_changes_only_the_given_fields() -> None:
    row = ModelCatalogEntry(id="codex/gpt-6-luna", cost_input_per_m=0.0, name="GPT-6 Luna")
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = row
    response = await _put("/api/models/catalog/codex/gpt-6-luna", {
        "subscription_rates": {"credits_per_m": {"input": 3.0, "cached_input": 0.3, "output": 15.0}},
    }, db)
    assert response.status_code == 200
    assert response.json() == {"id": "codex/gpt-6-luna", "created": False, "fields": ["subscription_rates"]}
    assert row.subscription_rates == {"credits_per_m": {"input": 3.0, "cached_input": 0.3, "output": 15.0}}
    assert row.name == "GPT-6 Luna"
    db.add.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_model_is_inserted_as_a_manual_row() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = None
    response = await _put("/api/models/catalog/xai/grok-5", {"alias": "grok5", "name": "Grok 5", "provider": "xai"}, db)
    assert response.status_code == 200
    added = db.add.call_args.args[0]
    assert (added.id, added.source, added.provider) == ("xai/grok-5", "manual", "xai")


@pytest.mark.asyncio
async def test_unknown_catalog_field_is_rejected() -> None:
    db = AsyncMock()
    response = await _put("/api/models/catalog/xai/grok-5", {"price": 1}, db)
    assert response.status_code == 422
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_alias_must_point_at_a_catalog_model() -> None:
    db = AsyncMock()
    db.get.return_value = None
    response = await _put("/api/models/aliases/fast", {"model_id": "nope"}, db)
    assert response.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_alias_is_repointed_in_place() -> None:
    alias = ModelAlias(alias="flash", model_id="gemini-3.7-flash", alias_type="seed")
    db = AsyncMock()
    db.add = MagicMock()
    db.get.side_effect = [ModelCatalogEntry(id="gemini-3.8-flash"), alias]
    response = await _put("/api/models/aliases/Flash", {"model_id": "gemini-3.8-flash"}, db)
    assert response.status_code == 200
    assert alias.model_id == "gemini-3.8-flash"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_catalog_writes_need_a_verified_service_client() -> None:
    async def override_db():
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/models/aliases/flash", json={"model_id": "gemini-3.8-flash"},
                                        headers={"X-Client-Id": "portfolio-ai"})
    finally:
        app.dependency_overrides.clear()
    assert 400 <= response.status_code < 500


@pytest.mark.asyncio
async def test_create_may_name_its_own_source() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.get.return_value = None
    response = await _put("/api/models/catalog/xai/grok-5", {"name": "Grok 5", "source": "enrichment"}, db)
    assert response.status_code == 200
    assert db.add.call_args.args[0].source == "enrichment"
