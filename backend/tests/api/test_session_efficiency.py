"""Pinned window/query contract on the existing admin router."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.admin import router
from app.db import get_db


@pytest.mark.asyncio
async def test_pinned_filtered_window_and_validation():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: None
    with patch("app.services.admin_activity_cost.build_activity_cost_snapshot", new_callable=AsyncMock, return_value={}) as build:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/admin/session-efficiency", params={
                "until": "2026-10-22T12:00:00Z", "hours": 1, "project_id": "project", "provider": "codex", "model": "fixture-model", "session_id": "s",
            })
            assert response.status_code == 200
            assert response.json()["filters"]["session_id"] == "s"
            assert build.call_args.kwargs["cutoff"] == datetime(2026, 10, 22, 11, tzinfo=UTC)
            assert build.call_args.kwargs["now"] == datetime(2026, 10, 22, 12, tzinfo=UTC)
            assert build.call_args.kwargs["project_id"] == "project"
            assert build.call_args.kwargs["provider"] == "codex"
            assert build.call_args.kwargs["model"] == "fixture-model"
            assert build.call_args.kwargs["session_id"] == "s"
            for params in ({"until": "2026-10-22T12:00:00"}, {"until": "2099-01-01T00:00:00Z"}, {"hours": 0}, {"limit": 21}):
                assert (await client.get("/api/admin/session-efficiency", params=params)).status_code == 422
            assert build.call_count == 1
