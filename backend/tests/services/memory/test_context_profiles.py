from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.services.memory import context_profiles


@pytest.mark.asyncio
async def test_policy_cache_without_db_uses_managed_async_session(monkeypatch) -> None:
    context_profiles.invalidate_policy_cache()
    calls: dict[str, Any] = {"entered": 0, "exited": 0, "loaded_with": None}

    @asynccontextmanager
    async def fake_async_session() -> AsyncGenerator[str]:
        calls["entered"] += 1
        try:
            yield "managed-session"
        finally:
            calls["exited"] += 1

    async def fake_load_policy_cache(session: str) -> dict[str, tuple[int | None, int | None, int | None]]:
        calls["loaded_with"] = session
        return {"agent_runtime": (1, 2, 3)}

    monkeypatch.setattr(context_profiles, "async_session", fake_async_session)
    monkeypatch.setattr(context_profiles, "_load_policy_cache", fake_load_policy_cache)

    cache = await context_profiles._ensure_policy_cache(None)

    assert cache == {"agent_runtime": (1, 2, 3)}
    assert calls == {"entered": 1, "exited": 1, "loaded_with": "managed-session"}
    context_profiles.invalidate_policy_cache()
