from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock

import pytest

from app.services.telegram_bot_service import (
    TELEGRAM_CHAT_MAX_TURNS,
    AgentHubTelegramBot,
    allowed_start_text,
    blocked_chat_text,
    current_session_id_text,
    reset_confirmation_text,
    select_latest_session_id,
    text_only_v1_reply,
)


def test_blocked_chat_text_includes_chat_id() -> None:
    assert blocked_chat_text("123") == "This chat is not authorized yet. Chat ID: 123. Ask the operator to add it in Agent Hub."


def test_text_only_reply_matches_contract() -> None:
    assert text_only_v1_reply() == "This bot supports text messages only in v1."


def test_reset_confirmation_matches_contract() -> None:
    assert reset_confirmation_text() == "Conversation reset. Your next text message will start a fresh Jenny conversation."


def test_allowed_start_text_mentions_binding_and_commands() -> None:
    text = allowed_start_text(chat_id="123", reports_bound=False)
    assert "Jenny connected" in text
    assert "Chat ID: 123" in text
    assert "Reports bound: no" in text
    assert "/status" in text
    assert "/reset" in text


def test_current_session_id_text_handles_missing_session() -> None:
    assert current_session_id_text(None) == "Current session id: none"


def test_select_latest_session_id_prefers_updated_then_created_then_id() -> None:
    sessions = [
        {"id": "a", "updated_at": "2026-04-22T14:00:00+00:00", "created_at": "2026-04-22T13:00:00+00:00"},
        {"id": "b", "updated_at": "2026-04-22T14:05:00+00:00", "created_at": "2026-04-22T13:30:00+00:00"},
        {"id": "c", "updated_at": "2026-04-22T14:05:00+00:00", "created_at": "2026-04-22T13:45:00+00:00"},
    ]
    assert select_latest_session_id(sessions) == "c"


@pytest.mark.asyncio
async def test_reply_uses_shared_delivery_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeRedis:
        async def close(self) -> None:
            return None

    update = types.SimpleNamespace(
        effective_chat=types.SimpleNamespace(id=123),
        effective_message=types.SimpleNamespace(message_id=77),
    )
    send_mock = AsyncMock(return_value=1)

    monkeypatch.setattr("app.services.telegram_bot_service.aioredis.from_url", lambda *args, **kwargs: _FakeRedis())
    monkeypatch.setattr("app.services.telegram_bot_service.send_rendered_message", send_mock)

    bot = AgentHubTelegramBot()
    await bot._reply(update, "hello", bot=AsyncMock())

    send_mock.assert_awaited_once()
    await_args = send_mock.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["chat_id"] == "123"
    assert kwargs["reply_to_message_id"] == 77
    assert kwargs["text"] == "hello"
    assert kwargs["disable_link_previews"] is False


@pytest.mark.asyncio
async def test_complete_text_requests_live_tool_enabled_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeRedis:
        async def close(self) -> None:
            return None

        async def get(self, _key: str) -> None:
            return None

        async def set(self, _key: str, _value: str) -> None:
            return None

        async def delete(self, _key: str) -> None:
            return None

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"session_id": "sess-telegram", "content": "All good"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            captured["base_url"] = kwargs.get("base_url")
            captured["headers"] = kwargs.get("headers")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

        async def post(self, path: str, json: dict[str, object]):
            captured["path"] = path
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr("app.services.telegram_bot_service.aioredis.from_url", lambda *args, **kwargs: _FakeRedis())
    monkeypatch.setattr("app.services.telegram_bot_service.httpx.AsyncClient", _FakeAsyncClient)

    bot = AgentHubTelegramBot()
    resolve_mock = AsyncMock(return_value=None)
    store_mock = AsyncMock()
    monkeypatch.setattr(bot, "_resolve_session_id", resolve_mock)
    monkeypatch.setattr(bot, "_store_session_id", store_mock)

    reply_text, session_id = await bot._complete_text(chat_id="123", text="Check live status")

    assert reply_text == "All good"
    assert session_id == "sess-telegram"
    assert captured["path"] == "/api/complete"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["project_id"] == "agent-hub"
    assert payload["agent_slug"] == "persona"
    assert payload["external_id"] == "telegram:dm:123"
    assert payload["use_memory"] is True
    assert payload["enable_caching"] is False
    assert payload["skip_cache"] is True
    assert payload["execute_tools"] is True
    assert payload["enable_programmatic_tools"] is True
    assert payload["max_turns"] == TELEGRAM_CHAT_MAX_TURNS
    store_mock.assert_awaited_once_with("123", "sess-telegram")


@pytest.mark.asyncio
async def test_heartbeat_replaces_malformed_existing_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _FakeRedis:
        async def close(self) -> None:
            return None

        async def get(self, _key: str) -> str:
            return "not-json"

        async def set(self, key: str, value: str) -> None:
            captured[key] = value

    monkeypatch.setattr("app.services.telegram_bot_service.aioredis.from_url", lambda *args, **kwargs: _FakeRedis())

    bot = AgentHubTelegramBot()
    bot.bot_username = "jenny_test_bot"
    await bot.heartbeat()

    payload = json.loads(next(iter(captured.values())))
    assert payload["runner_status"] == "polling"
    assert payload["last_error"] is None
    assert payload["bot_username"] == "jenny_test_bot"


@pytest.mark.asyncio
async def test_heartbeat_loop_runs_until_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeRedis:
        async def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.telegram_bot_service.aioredis.from_url", lambda *args, **kwargs: _FakeRedis())

    bot = AgentHubTelegramBot()
    calls = 0

    async def _heartbeat() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(bot, "heartbeat", _heartbeat)
    with pytest.raises(asyncio.CancelledError):
        await bot.heartbeat_loop(interval_seconds=0)

    assert calls == 2


@pytest.mark.asyncio
async def test_run_polling_writes_degraded_on_startup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeRedis:
        async def close(self) -> None:
            return None

    class _SessionCtx:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Filter:
        def __and__(self, _other):
            return self

        def __invert__(self):
            return self

    class _Application:
        job_queue = None
        updater = None

        def __init__(self) -> None:
            self.bot = types.SimpleNamespace(get_me=AsyncMock(side_effect=RuntimeError("telegram auth failed")))
            self.shutdown = AsyncMock()

        def add_handler(self, _handler) -> None:
            return None

        async def initialize(self) -> None:
            return None

    app_instance = _Application()

    class _Builder:
        def token(self, _token: str):
            return self

        def build(self):
            return app_instance

    telegram_ext = types.SimpleNamespace(
        Application=types.SimpleNamespace(builder=lambda: _Builder()),
        CommandHandler=lambda *args, **kwargs: object(),
        MessageHandler=lambda *args, **kwargs: object(),
        filters=types.SimpleNamespace(
            ChatType=types.SimpleNamespace(PRIVATE=_Filter()),
            TEXT=_Filter(),
            COMMAND=_Filter(),
        ),
    )

    monkeypatch.setattr("app.services.telegram_bot_service.aioredis.from_url", lambda *args, **kwargs: _FakeRedis())
    monkeypatch.setattr("app.services.telegram_bot_service.async_session", lambda: _SessionCtx())
    monkeypatch.setattr("app.services.telegram_bot_service.reconcile_first_party_clients", AsyncMock())
    monkeypatch.setattr(
        "app.services.telegram_bot_service.load_runtime_config",
        AsyncMock(return_value={"token": "token", "allowlist_error": None}),
    )
    monkeypatch.setitem(sys.modules, "telegram", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "telegram.ext", telegram_ext)

    bot = AgentHubTelegramBot()
    write_status = AsyncMock()
    monkeypatch.setattr(bot, "write_runner_status", write_status)

    with pytest.raises(RuntimeError, match="telegram auth failed"):
        await bot.run_polling()

    write_status.assert_awaited_with(runner_status="degraded", last_error="telegram auth failed")
    app_instance.shutdown.assert_awaited_once()
