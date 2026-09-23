"""Retired review routes remain visible and report unavailable."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.context_management import router as context_router
from app.api.memory_episodes import router as memory_router
from app.db import get_db
from app.services.api_key_auth import require_api_key


@pytest.mark.asyncio
async def test_retired_routes_return_410_and_manual_routes_remain_registered() -> None:
    app = FastAPI()
    app.include_router(context_router, prefix="/context")
    app.include_router(memory_router, prefix="/memory")
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_api_key] = lambda: None
    paths = {path for route in app.routes if (path := getattr(route, "path", None)) is not None}
    assert {"/context/manage/inventory", "/context/manage/preview", "/context/manage/save",
            "/context/manage/history", "/context/manage/changes/{change_id}/undo",
            "/memory/episode/{episode_id}/revisions"} <= paths

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        memory = await client.post("/memory/review/run", json={})
        curator = await client.post("/context/manage/review", json={
            "context": {"consumer_surface": "codex"}, "mode": "curator",
        })
        jev = await client.post("/context/manage/review", json={
            "context": {"consumer_surface": "codex"}, "mode": "jev",
        })
        reconcile = await client.post("/context/manage/maintenance", json={
            "context": {"consumer_surface": "codex"}, "action": "reconcile",
        })

    for response in (memory, curator, jev, reconcile):
        assert response.status_code == 410
        assert "retired" in response.json()["detail"]
    db.execute.assert_not_awaited()
