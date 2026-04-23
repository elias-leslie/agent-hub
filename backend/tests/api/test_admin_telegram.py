from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_db
from app.main import app

TEST_HEADERS = {
    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    "X-Source-Client": "pytest",
}


@pytest.fixture
async def client():
    mock_db = AsyncMock()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac, mock_db
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_status_requires_internal_header() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/admin/telegram/status")

    assert response.status_code == 403
    assert response.json()["error"] == "internal_only"


@pytest.mark.asyncio
async def test_get_status_returns_service_payload(client) -> None:
    ac, _ = client
    payload = {
        "configured": True,
        "bot_token_source": "stored",
        "bot_username": "jenny_test_bot",
        "allowed_chat_ids": ["123"],
        "allowed_chat_ids_source": "stored",
        "report_chat_id": "123",
        "report_chat_id_source": "stored",
        "runner_status": "unknown",
        "last_poll_at": None,
        "last_error": None,
    }

    with patch("app.api.admin_telegram.get_telegram_status", new=AsyncMock(return_value=payload)):
        response = await ac.get("/api/admin/telegram/status")

    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.asyncio
async def test_put_config_passes_only_present_keys_and_returns_status(client) -> None:
    ac, mock_db = client
    payload = {
        "configured": True,
        "bot_token_source": "env",
        "bot_username": None,
        "allowed_chat_ids": ["123", "456"],
        "allowed_chat_ids_source": "stored",
        "report_chat_id": None,
        "report_chat_id_source": None,
        "runner_status": "degraded",
        "last_poll_at": None,
        "last_error": "allowed_chat_ids is empty",
    }

    with patch(
        "app.api.admin_telegram.update_telegram_config",
        new=AsyncMock(return_value=payload),
    ) as mock_update:
        response = await ac.put(
            "/api/admin/telegram/config",
            json={"allowed_chat_ids": [123, "456"], "report_chat_id": None},
        )

    assert response.status_code == 200
    assert response.json() == payload
    mock_update.assert_awaited_once_with(
        mock_db,
        {"allowed_chat_ids": [123, "456"], "report_chat_id": None},
    )


@pytest.mark.asyncio
async def test_put_config_returns_400_for_handler_validation_error(client) -> None:
    ac, _ = client

    with patch(
        "app.api.admin_telegram.update_telegram_config",
        new=AsyncMock(side_effect=ValueError("allowed_chat_ids must be a JSON array")),
    ):
        response = await ac.put(
            "/api/admin/telegram/config",
            json={"allowed_chat_ids": ["123"]},
        )

    assert response.status_code == 400
    assert response.json()["message"] == "allowed_chat_ids must be a JSON array"


@pytest.mark.asyncio
async def test_put_config_keeps_fastapi_422_for_schema_errors(client) -> None:
    ac, _ = client

    response = await ac.put(
        "/api/admin/telegram/config",
        json={"allowed_chat_ids": "123"},
    )

    assert response.status_code == 422
