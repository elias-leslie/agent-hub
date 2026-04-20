"""Tests for the Codex OAuth adapter tool loop."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    StreamEvent,
    ToolCallResult,
)
from app.adapters.codex_auth import CodexCredentials
from app.adapters.codex_oauth import CodexOAuthAdapter, _convert_messages_to_input


def _build_codex_jwt(*, account_id: str = "acct", expires_at: float | None = None) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    payload: dict[str, Any] = {
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    if expires_at is not None:
        payload["exp"] = int(expires_at)
    payload_part = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{payload_part}.sig"


def test_convert_messages_to_input_normalizes_image_blocks() -> None:
    input_items, instructions = _convert_messages_to_input(
        [
            Message(role="system", content="System rules"),
            Message(
                role="user",
                content=[
                    {"type": "text", "text": "Check this"},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "abc123",
                        },
                    },
                ],
            ),
        ]
    )

    assert instructions == "System rules"
    assert input_items == [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Check this"},
                {"type": "input_image", "image_url": "data:image/png;base64,abc123"},
            ],
        }
    ]


class _FakeCredentialManager:
    def __init__(self, oauth_token: str | None, refresh_token: str | None) -> None:
        self.is_initialized = True
        self.values = {
            "codex:oauth_token": oauth_token,
            "codex:refresh_token": refresh_token,
        }

    def get(self, provider: str, credential_type: str) -> str | None:
        return self.values.get(f"{provider}:{credential_type}")

    def get_api_key(self, provider: str) -> str | None:
        return self.values.get(f"{provider}:api_key")

    def set(self, provider: str, credential_type: str, value: str) -> None:
        self.values[f"{provider}:{credential_type}"] = value


@pytest.mark.asyncio
async def test_complete_with_tools_emits_tool_events_and_done() -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    complete_from_input = AsyncMock(
        side_effect=[
            CompletionResult(
                content="Checking repo",
                model="gpt-5.4",
                provider="codex",
                input_tokens=12,
                output_tokens=4,
                finish_reason="tool_use",
                tool_calls=[ToolCallResult(id="call_1", name="read_file", input={"path": "README.md"})],
                thinking_content="Need the file first.",
            ),
            CompletionResult(
                content="Done",
                model="gpt-5.4",
                provider="codex",
                input_tokens=20,
                output_tokens=6,
                finish_reason="stop",
            ),
        ]
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock(return_value="readme contents")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="Read the README")],
        model="codex/gpt-5.4",
        tools=[{"name": "read_file", "description": "Read a file", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=3,
    ):
        events.append(event)

    event_types = [event.type for event in events]
    assert event_types == ["thinking", "content", "tool_use", "tool_result", "content", "done"]
    assert events[2].tool_name == "read_file"
    assert events[2].tool_input == {"path": "README.md"}
    assert events[3].content == "readme contents"
    tool_handler.assert_awaited_once_with("read_file", {"path": "README.md"})


@pytest.mark.asyncio
async def test_complete_with_tools_max_turns_exhaustion() -> None:
    """complete_with_tools emits done/max_turns when tool_use never resolves."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    # Always returns tool_use so the loop never terminates naturally.
    complete_from_input = AsyncMock(
        return_value=CompletionResult(
            content="",
            model="gpt-5.4",
            provider="codex",
            input_tokens=5,
            output_tokens=2,
            finish_reason="tool_use",
            tool_calls=[ToolCallResult(id="call_x", name="noop", input={})],
        )
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock(return_value="ok")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="loop forever")],
        model="codex/gpt-5.4",
        tools=[{"name": "noop", "description": "noop", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=2,
    ):
        events.append(event)

    done_event = events[-1]
    assert done_event.type == "done"
    assert done_event.finish_reason == "max_turns"


@pytest.mark.asyncio
async def test_complete_with_tools_empty_tool_calls_ends_immediately() -> None:
    """complete_with_tools ends immediately when finish_reason is done and tool_calls is empty."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    complete_from_input = AsyncMock(
        return_value=CompletionResult(
            content="All done",
            model="gpt-5.4",
            provider="codex",
            input_tokens=8,
            output_tokens=3,
            finish_reason="done",
            tool_calls=[],
        )
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock()

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="hi")],
        model="codex/gpt-5.4",
        tools=[],
        tool_handler=tool_handler,
        max_turns=5,
    ):
        events.append(event)

    assert events[-1].type == "done"
    assert events[-1].finish_reason == "done"
    tool_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_with_tools_multiple_tool_calls_per_turn() -> None:
    """tool_handler is awaited once for each tool call in a single turn."""
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    complete_from_input = AsyncMock(
        side_effect=[
            CompletionResult(
                content="",
                model="gpt-5.4",
                provider="codex",
                input_tokens=10,
                output_tokens=5,
                finish_reason="tool_use",
                tool_calls=[
                    ToolCallResult(id="call_a", name="tool_a", input={"x": 1}),
                    ToolCallResult(id="call_b", name="tool_b", input={"y": 2}),
                    ToolCallResult(id="call_c", name="tool_c", input={"z": 3}),
                ],
            ),
            CompletionResult(
                content="Done",
                model="gpt-5.4",
                provider="codex",
                input_tokens=15,
                output_tokens=4,
                finish_reason="stop",
            ),
        ]
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock(return_value="result")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="run tools")],
        model="codex/gpt-5.4",
        tools=[
            {"name": "tool_a", "description": "a", "input_schema": {"type": "object"}},
            {"name": "tool_b", "description": "b", "input_schema": {"type": "object"}},
            {"name": "tool_c", "description": "c", "input_schema": {"type": "object"}},
        ],
        tool_handler=tool_handler,
        max_turns=5,
    ):
        events.append(event)

    tool_use_events = [e for e in events if e.type == "tool_use"]
    tool_result_events = [e for e in events if e.type == "tool_result"]
    assert len(tool_use_events) == 3
    assert len(tool_result_events) == 3
    assert tool_handler.await_count == 3
    tool_handler.assert_any_await("tool_a", {"x": 1})
    tool_handler.assert_any_await("tool_b", {"y": 2})
    tool_handler.assert_any_await("tool_c", {"z": 3})


@pytest.mark.asyncio
async def test_complete_with_tools_retries_empty_final_response_once() -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    complete_from_input = AsyncMock(
        side_effect=[
            CompletionResult(
                content="",
                model="gpt-5.4",
                provider="codex",
                input_tokens=10,
                output_tokens=5,
                finish_reason="tool_use",
                tool_calls=[ToolCallResult(id="call_x", name="noop", input={})],
            ),
            CompletionResult(
                content="",
                model="gpt-5.4",
                provider="codex",
                input_tokens=12,
                output_tokens=1,
                finish_reason="done",
                tool_calls=[],
            ),
            CompletionResult(
                content="No further changes needed.",
                model="gpt-5.4",
                provider="codex",
                input_tokens=14,
                output_tokens=4,
                finish_reason="done",
                tool_calls=[],
            ),
        ]
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock(return_value="ok")

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="loop once")],
        model="codex/gpt-5.4",
        tools=[{"name": "noop", "description": "noop", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=5,
    ):
        events.append(event)

    assert any(e.type == "content" and e.content == "No further changes needed." for e in events)
    assert events[-1].type == "done"
    assert complete_from_input.await_count == 3


@pytest.mark.asyncio
async def test_complete_with_tools_disables_transport_timeout_for_tool_turns() -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )
    complete_from_input = AsyncMock(
        return_value=CompletionResult(
            content="Done",
            model="gpt-5.4",
            provider="codex",
            input_tokens=8,
            output_tokens=3,
            finish_reason="done",
            tool_calls=[],
        )
    )
    cast(Any, adapter)._complete_from_input = complete_from_input

    tool_handler = AsyncMock()

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="hi")],
        model="codex/gpt-5.4",
        tools=[],
        tool_handler=tool_handler,
        max_turns=2,
    ):
        events.append(event)

    assert events[-1].type == "done"
    assert complete_from_input.await_args is not None
    assert complete_from_input.await_args.kwargs["request_timeout"] is None


@pytest.mark.asyncio
async def test_complete_with_tools_allows_slow_post_tool_progress_without_force_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )

    async def slow_complete(**kwargs):
        assert kwargs["request_timeout"] is None
        await asyncio.sleep(0.05)
        return CompletionResult(
            content="Done",
            model="gpt-5.4",
            provider="codex",
            input_tokens=8,
            output_tokens=3,
            finish_reason="done",
            tool_calls=[],
        )

    monkeypatch.setattr(adapter, "_complete_from_input", slow_complete)

    tool_handler = AsyncMock()

    events = []
    async for event in adapter.complete_with_tools(
        messages=[Message(role="user", content="hang")],
        model="codex/gpt-5.4",
        tools=[{"name": "noop", "description": "noop", "input_schema": {"type": "object"}}],
        tool_handler=tool_handler,
        max_turns=2,
    ):
        events.append(event)

    assert len(events) == 2
    assert [event.type for event in events] == ["content", "done"]
    tool_handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_complete_from_input_uses_owned_response_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )

    lifecycle: list[str] = []

    class FakeSession:
        def __init__(self, **_: object) -> None:
            self.response = object()

        async def start(self) -> None:
            lifecycle.append("start")

        async def interrupt(self) -> None:
            lifecycle.append("interrupt")

        async def close(self) -> None:
            lifecycle.append("close")

    async def fake_collect_completion(
        response: object,
        resolved_model: str,
    ) -> CompletionResult:
        assert response is not None
        assert resolved_model == "gpt-5.4"
        return CompletionResult(
            content="Done",
            model=resolved_model,
            provider="codex",
            input_tokens=11,
            output_tokens=7,
            finish_reason="stop",
        )

    monkeypatch.setattr("app.adapters.codex_oauth._CodexResponseSession", FakeSession)
    monkeypatch.setattr("app.adapters.codex_oauth.collect_completion", fake_collect_completion)

    result = await adapter._complete_from_input(
        input_items=[{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
        instructions=None,
        resolved_model="gpt-5.4",
        max_tokens=None,
        temperature=1.0,
    )

    assert result.content == "Done"
    assert result.finish_reason == "stop"
    assert lifecycle == ["start", "close"]


@pytest.mark.asyncio
async def test_stream_preserves_events_and_closes_owned_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )

    lifecycle: list[str] = []

    class FakeSession:
        def __init__(self, **_: object) -> None:
            self.response = object()

        async def start(self) -> None:
            lifecycle.append("start")

        async def interrupt(self) -> None:
            lifecycle.append("interrupt")

        async def close(self) -> None:
            lifecycle.append("close")

    async def fake_iter_stream_events(response: object) -> AsyncIterator[StreamEvent]:
        assert response is not None
        yield StreamEvent(type="content", content="hello")
        yield StreamEvent(type="done", input_tokens=3, output_tokens=2, finish_reason="stop")

    monkeypatch.setattr("app.adapters.codex_oauth._CodexResponseSession", FakeSession)
    monkeypatch.setattr("app.adapters.codex_oauth.iter_stream_events", fake_iter_stream_events)

    events = []
    async for event in adapter.stream(
        messages=[Message(role="user", content="hello")],
        model="codex/gpt-5.4",
    ):
        events.append(event)

    assert [(event.type, event.content, event.finish_reason) for event in events] == [
        ("content", "hello", None),
        ("done", "", "stop"),
    ]
    assert lifecycle == ["start", "close"]


@pytest.mark.asyncio
async def test_stream_interrupts_owned_session_on_abort_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token="token",
            refresh_token="refresh",
            account_id="acct",
            expires_at=9_999_999_999,
        )
    )

    lifecycle: list[str] = []
    holder: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **_: object) -> None:
            self.response = object()
            self.interrupted = asyncio.Event()
            holder["session"] = self

        async def start(self) -> None:
            lifecycle.append("start")

        async def interrupt(self) -> None:
            lifecycle.append("interrupt")
            self.interrupted.set()

        async def close(self) -> None:
            lifecycle.append("close")

    async def fake_iter_stream_events(response: object) -> AsyncIterator[StreamEvent]:
        assert response is not None
        yield StreamEvent(type="content", content="hello")
        session = holder["session"]
        assert isinstance(session, FakeSession)
        await session.interrupted.wait()
        raise httpx.ReadError("stream closed during interrupt")

    monkeypatch.setattr("app.adapters.codex_oauth._CodexResponseSession", FakeSession)
    monkeypatch.setattr("app.adapters.codex_oauth.iter_stream_events", fake_iter_stream_events)

    abort_event = asyncio.Event()
    events = []
    async for event in adapter.stream(
        messages=[Message(role="user", content="hello")],
        model="codex/gpt-5.4",
        abort_event=abort_event,
    ):
        events.append(event)
        if event.type == "content":
            abort_event.set()

    assert [(event.type, event.content, event.finish_reason) for event in events] == [
        ("content", "hello", None),
        ("done", "", "cancelled"),
    ]
    assert lifecycle == ["start", "interrupt", "close"]


def test_init_derives_expiry_from_legacy_stored_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    expires_at = time.time() + 3600
    cm = _FakeCredentialManager(_build_codex_jwt(expires_at=expires_at), "refresh-token")

    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)

    adapter = CodexOAuthAdapter()

    assert adapter._credentials is not None
    assert adapter._credentials.refresh_token == "refresh-token"
    assert adapter._credentials.expires_at == pytest.approx(expires_at, abs=1)


def test_get_credentials_reads_latest_manager_values_after_adapter_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_expiry = time.time() + 1800
    second_expiry = time.time() + 7200
    cm = _FakeCredentialManager(_build_codex_jwt(expires_at=first_expiry), "refresh-token-1")

    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)

    adapter = CodexOAuthAdapter()
    original = adapter._get_credentials()
    assert original.refresh_token == "refresh-token-1"

    cm.set("codex", "oauth_token", _build_codex_jwt(expires_at=second_expiry))
    cm.set("codex", "refresh_token", "refresh-token-2")

    updated = adapter._get_credentials()

    assert updated.refresh_token == "refresh-token-2"
    assert updated.expires_at == pytest.approx(second_expiry, abs=1)


@pytest.mark.asyncio
async def test_ensure_fresh_credentials_persists_refreshed_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_at = time.time() - 300
    refreshed_at = time.time() + 3600
    adapter = CodexOAuthAdapter(
        credentials=CodexCredentials(
            access_token=_build_codex_jwt(expires_at=expired_at),
            refresh_token="old-refresh",
            account_id="acct",
            expires_at=expired_at,
        )
    )
    refreshed = CodexCredentials(
        access_token=_build_codex_jwt(expires_at=refreshed_at),
        refresh_token="new-refresh",
        account_id="acct",
        expires_at=refreshed_at,
    )
    assert adapter._credentials is not None
    cm = _FakeCredentialManager(adapter._credentials.access_token, "old-refresh")
    upsert_calls: list[tuple[str, str, str]] = []

    class _FakeAsyncSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    async def _fake_upsert(_db: object, provider: str, credential_type: str, value: str) -> None:
        upsert_calls.append((provider, credential_type, value))

    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)
    monkeypatch.setattr("app.adapters.codex_oauth.read_cached_token", lambda _refresh: None)
    monkeypatch.setattr("app.adapters.codex_oauth.write_cached_token", lambda _creds: None)
    monkeypatch.setattr("app.adapters.codex_oauth.refresh_access_token", AsyncMock(return_value=refreshed))
    monkeypatch.setattr("app.db.async_session", lambda: _FakeAsyncSession())
    monkeypatch.setattr("app.services.credential_upsert.upsert_credential", _fake_upsert)

    result = await adapter._ensure_fresh_credentials()

    assert result.access_token == refreshed.access_token
    assert json.loads(cm.values["codex:oauth_token"]) == {
        "access_token": refreshed.access_token,
        "expires_at": refreshed.expires_at,
    }
    assert cm.values["codex:refresh_token"] == "new-refresh"
    assert ("codex", "refresh_token", "new-refresh") in upsert_calls
    oauth_writes = [value for provider, kind, value in upsert_calls if provider == "codex" and kind == "oauth_token"]
    assert len(oauth_writes) == 1
    assert json.loads(oauth_writes[0]) == {
        "access_token": refreshed.access_token,
        "expires_at": refreshed.expires_at,
    }


@pytest.mark.asyncio
async def test_ensure_fresh_credentials_reloads_db_after_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_at = time.time() - 300
    recovered_at = time.time() + 7200
    stale_token = _build_codex_jwt(expires_at=expired_at)
    recovered_token = _build_codex_jwt(expires_at=recovered_at)

    class _ReloadingCredentialManager(_FakeCredentialManager):
        def __init__(self) -> None:
            super().__init__(stale_token, "stale-refresh")
            self.load_calls = 0

        async def load(self, _db: object) -> int:
            self.load_calls += 1
            self.set("codex", "oauth_token", recovered_token)
            self.set("codex", "refresh_token", "fresh-refresh")
            return 2

    cm = _ReloadingCredentialManager()
    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)
    monkeypatch.setattr(
        "app.adapters.codex_oauth.refresh_access_token",
        AsyncMock(side_effect=RuntimeError("Codex token refresh failed (HTTP 401)")),
    )

    class _FakeAsyncSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr("app.db.async_session", lambda: _FakeAsyncSession())

    adapter = CodexOAuthAdapter()

    result = await adapter._ensure_fresh_credentials()

    assert cm.load_calls == 1
    assert result.refresh_token == "fresh-refresh"
    assert result.expires_at == pytest.approx(recovered_at, abs=1)


@pytest.mark.asyncio
async def test_ensure_fresh_credentials_recovers_from_local_auth_file_after_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_at = time.time() - 300
    recovered_at = time.time() + 5400
    stale_token = _build_codex_jwt(expires_at=expired_at)
    recovered = CodexCredentials(
        access_token=_build_codex_jwt(expires_at=recovered_at),
        refresh_token="local-refresh",
        account_id="acct",
        expires_at=recovered_at,
    )

    class _StaleCredentialManager(_FakeCredentialManager):
        async def load(self, _db: object) -> int:
            return 2

    cm = _StaleCredentialManager(stale_token, "stale-refresh")
    upsert_calls: list[tuple[str, str, str]] = []

    class _FakeAsyncSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    async def _fake_upsert(_db: object, provider: str, credential_type: str, value: str) -> None:
        upsert_calls.append((provider, credential_type, value))

    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)
    monkeypatch.setattr("app.adapters.codex_oauth.read_cached_token", lambda _refresh: None)
    monkeypatch.setattr("app.adapters.codex_oauth.write_cached_token", lambda _creds: None)
    monkeypatch.setattr(
        "app.adapters.codex_oauth.refresh_access_token",
        AsyncMock(side_effect=RuntimeError("Codex token refresh failed (HTTP 401)")),
    )
    monkeypatch.setattr("app.db.async_session", lambda: _FakeAsyncSession())
    monkeypatch.setattr("app.services.credential_upsert.upsert_credential", _fake_upsert)
    monkeypatch.setattr(
        "app.adapters.codex_oauth.load_local_codex_auth_credentials",
        lambda: recovered,
        raising=False,
    )

    adapter = CodexOAuthAdapter()

    result = await adapter._ensure_fresh_credentials()

    assert result.access_token == recovered.access_token
    assert result.refresh_token == "local-refresh"
    assert json.loads(cm.values["codex:oauth_token"]) == {
        "access_token": recovered.access_token,
        "expires_at": recovered.expires_at,
    }
    assert cm.values["codex:refresh_token"] == "local-refresh"
    assert ("codex", "refresh_token", "local-refresh") in upsert_calls


@pytest.mark.asyncio
async def test_ensure_fresh_credentials_rejects_expired_local_auth_file_after_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_at = time.time() - 300
    stale_token = _build_codex_jwt(expires_at=expired_at)
    expired_local = CodexCredentials(
        access_token=_build_codex_jwt(expires_at=expired_at - 60),
        refresh_token="expired-local-refresh",
        account_id="acct",
        expires_at=expired_at - 60,
    )

    class _StaleCredentialManager(_FakeCredentialManager):
        async def load(self, _db: object) -> int:
            return 2

    cm = _StaleCredentialManager(stale_token, "stale-refresh")
    upsert_calls: list[tuple[str, str, str]] = []

    class _FakeAsyncSession:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    async def _fake_upsert(_db: object, provider: str, credential_type: str, value: str) -> None:
        upsert_calls.append((provider, credential_type, value))

    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)
    monkeypatch.setattr("app.adapters.codex_oauth.read_cached_token", lambda _refresh: None)
    monkeypatch.setattr("app.adapters.codex_oauth.write_cached_token", lambda _creds: None)
    monkeypatch.setattr(
        "app.adapters.codex_oauth.refresh_access_token",
        AsyncMock(side_effect=RuntimeError("Codex token refresh failed (HTTP 401)")),
    )
    monkeypatch.setattr("app.db.async_session", lambda: _FakeAsyncSession())
    monkeypatch.setattr("app.services.credential_upsert.upsert_credential", _fake_upsert)
    monkeypatch.setattr(
        "app.adapters.codex_oauth.load_local_codex_auth_credentials",
        lambda: expired_local,
        raising=False,
    )

    adapter = CodexOAuthAdapter()

    with pytest.raises(AuthenticationError):
        await adapter._ensure_fresh_credentials()

    assert cm.values["codex:refresh_token"] == "stale-refresh"
    assert upsert_calls == []


@pytest.mark.asyncio
async def test_health_check_fails_for_expired_credential_without_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cm = _FakeCredentialManager(_build_codex_jwt(expires_at=time.time() - 300), None)
    monkeypatch.setattr("app.services.credential_manager.get_credential_manager", lambda: cm)

    adapter = CodexOAuthAdapter()

    assert await adapter.health_check() is False
