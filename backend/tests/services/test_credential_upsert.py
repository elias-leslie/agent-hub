from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.credential_upsert import (
    reset_provider_cooldown_after_credential_change,
    upsert_credential,
)


@pytest.mark.asyncio
async def test_auth_credential_change_resets_provider_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    reset = AsyncMock()
    monkeypatch.setattr("app.services.agent_routing_completion.reset_provider_rate_limit_cooldown", reset)

    await reset_provider_cooldown_after_credential_change("codex", "oauth_token")

    reset.assert_awaited_once_with("codex")


@pytest.mark.asyncio
async def test_non_auth_credential_change_does_not_reset_provider_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    reset = AsyncMock()
    monkeypatch.setattr("app.services.agent_routing_completion.reset_provider_rate_limit_cooldown", reset)

    await reset_provider_cooldown_after_credential_change("cloudflare", "account_id")

    reset.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_credential_resets_provider_cooldown_after_update(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = SimpleNamespace(id=14, credential_type="refresh_token")
    manager = SimpleNamespace(set=MagicMock())
    reset = AsyncMock()
    update = AsyncMock()

    monkeypatch.setattr("app.services.credential_upsert.list_credentials_async", AsyncMock(return_value=[existing]))
    monkeypatch.setattr("app.services.credential_upsert.update_credential_async", update)
    monkeypatch.setattr("app.services.credential_upsert.get_credential_manager", lambda: manager)
    monkeypatch.setattr("app.services.credential_upsert.reset_provider_cooldown_after_credential_change", reset)

    db = AsyncMock()
    await upsert_credential(db, "codex", "refresh_token", "new-value")

    update.assert_awaited_once_with(db, 14, "new-value")
    manager.set.assert_called_once_with("codex", "refresh_token", "new-value")
    reset.assert_awaited_once_with("codex", "refresh_token")
