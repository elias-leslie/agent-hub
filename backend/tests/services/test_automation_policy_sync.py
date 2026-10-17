"""A central edit of owner-registered policy keys reaches the owner before its next run."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.automation_dispatch import sync_owner_policies


@pytest.mark.asyncio
async def test_owner_policy_sync_sends_only_owner_keys_and_persists_acknowledged_revision():
    policy = SimpleNamespace(
        project_id="jobinator-4000", enabled=False,
        config={"screening_cap": 200, "classification_cap": 40, "daily_limit": 9},
        revision=3, sync_revision=2,
    )
    definition = SimpleNamespace(
        workflow_key="jobinator-4000/nightly_screen", version=1, owner_project_id="jobinator-4000",
        policy_schema={"x-owner-keys": ["classification_cap", "screening_cap"]},
    )
    read_db = AsyncMock()
    read_db.get.return_value = policy
    read_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=[definition]),
    )))
    write_db = AsyncMock()
    write_db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=policy))
    read_context = MagicMock()
    read_context.__aenter__ = AsyncMock(return_value=read_db)
    read_context.__aexit__ = AsyncMock(return_value=None)
    write_context = MagicMock()
    write_context.__aenter__ = AsyncMock(return_value=write_db)
    write_context.__aexit__ = AsyncMock(return_value=None)
    response = MagicMock()
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.services.automation_dispatch.async_session", side_effect=[read_context, write_context]),
        patch("app.services.automation_dispatch._owner_api_base", return_value="http://localhost:8014/api"),
        patch("app.services.automation_dispatch.httpx.AsyncClient", return_value=client),
        patch("app.services.automation_dispatch.settings.internal_service_secret", "test-secret"),
    ):
        assert await sync_owner_policies()

    client.post.assert_awaited_once_with(
        "http://localhost:8014/api/automations/policy/sync",
        json={"revision": 3, "enabled": False, "config": {
            "screening_cap": 200, "classification_cap": 40,
        }},
        headers={"X-Agent-Hub-Internal": "test-secret"},
    )
    assert policy.sync_revision == 3
    write_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_without_registered_keys_is_never_synced():
    definition = SimpleNamespace(
        workflow_key="portfolio-ai/jenny_weekly_price_check", version=1, owner_project_id="portfolio-ai",
        policy_schema={"type": "object"},
    )
    read_db = AsyncMock()
    read_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(
        all=MagicMock(return_value=[definition]),
    )))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=read_db)
    context.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.services.automation_dispatch.async_session", return_value=context),
        patch("app.services.automation_dispatch.httpx.AsyncClient") as client,
    ):
        assert await sync_owner_policies()
    client.assert_not_called()
    read_db.get.assert_not_awaited()
