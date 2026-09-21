from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.native_continuation_runtime as native_runtime
from app.adapters.codex_auth import CodexCredentials
from app.services.native_continuation_runtime import (
    NATIVE_TOOL_POLICY_HASH,
    NativeRuntimeKey,
    NativeRuntimeLost,
    NativeRuntimeManager,
    NativeTurnObservation,
    NativeTurnUsage,
    _login_with_agent_hub_auth,
    _Protocol,
    _turn_usage,
)


@pytest.mark.asyncio
async def test_external_auth_refresh_uses_agent_hub_pair_without_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = CodexCredentials("initial-access", "private-initial", "account")
    rotated = CodexCredentials("rotated-access", "private-rotated", "account")
    protocol = _Protocol(MagicMock())
    protocol.set_external_auth(initial)
    send = AsyncMock()
    protocol.send = send  # type: ignore[method-assign]
    refresh = AsyncMock(return_value=rotated)
    monkeypatch.setattr(
        native_runtime,
        "ensure_fresh_codex_credentials",
        refresh,
    )

    await protocol._refresh_external_auth(
        {
            "id": 7,
            "params": {
                "reason": "unauthorized",
                "previousAccountId": "account",
            },
        }
    )

    refresh.assert_awaited_once_with(
        force_refresh=True,
        stale_access_token="initial-access",
        expected_account_id="account",
    )
    assert send.await_args is not None
    response = send.await_args.args[0]
    assert response["result"]["accessToken"] == "rotated-access"
    assert "refresh" not in json.dumps(response).lower()


@pytest.mark.asyncio
async def test_external_auth_refresh_rejects_account_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = _Protocol(MagicMock())
    protocol.set_external_auth(
        CodexCredentials("initial-access", "private-refresh", "account-a")
    )
    send = AsyncMock()
    protocol.send = send  # type: ignore[method-assign]
    refresh = AsyncMock()
    monkeypatch.setattr(native_runtime, "ensure_fresh_codex_credentials", refresh)

    with pytest.raises(native_runtime.NativeRuntimeError, match="different account"):
        await protocol._refresh_external_auth(
            {
                "id": 8,
                "params": {
                    "reason": "unauthorized",
                    "previousAccountId": "account-b",
                },
            }
        )

    refresh.assert_not_awaited()
    assert send.await_args is not None
    assert send.await_args.args[0]["error"]["code"] == -32001


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        pytest.param(None, id="missing-params"),
        pytest.param({}, id="missing-reason-and-account"),
        pytest.param(
            {"reason": "expired", "previousAccountId": "account"},
            id="unsupported-reason",
        ),
        pytest.param(
            {"reason": "unauthorized", "previousAccountId": None},
            id="missing-bound-account",
        ),
    ],
)
async def test_external_auth_refresh_rejects_invalid_contract(
    monkeypatch: pytest.MonkeyPatch,
    params: object,
) -> None:
    protocol = _Protocol(MagicMock())
    protocol.set_external_auth(
        CodexCredentials("initial-access", "private-refresh", "account")
    )
    send = AsyncMock()
    protocol.send = send  # type: ignore[method-assign]
    refresh = AsyncMock()
    monkeypatch.setattr(native_runtime, "ensure_fresh_codex_credentials", refresh)
    message: dict[str, object] = {"id": 9}
    if params is not None:
        message["params"] = params

    with pytest.raises(native_runtime.NativeRuntimeError):
        await protocol._refresh_external_auth(message)

    refresh.assert_not_awaited()
    assert send.await_args is not None
    assert send.await_args.args[0]["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_external_auth_refresh_timeout_cancels_callback_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = _Protocol(MagicMock())
    protocol.set_external_auth(
        CodexCredentials("initial-access", "private-refresh", "account")
    )
    send = AsyncMock()
    protocol.send = send  # type: ignore[method-assign]
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def delayed_refresh(**_kwargs: object) -> CodexCredentials:
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return CodexCredentials("rotated-access", "private-rotated", "account")

    monkeypatch.setattr(
        native_runtime, "ensure_fresh_codex_credentials", delayed_refresh
    )
    monkeypatch.setattr(
        native_runtime, "_EXTERNAL_AUTH_CALLBACK_BUDGET_SECONDS", 0.001
    )

    with pytest.raises(native_runtime.NativeRuntimeError, match="deadline"):
        await protocol._refresh_external_auth(
            {
                "id": 10,
                "params": {
                    "reason": "unauthorized",
                    "previousAccountId": "account",
                },
            }
        )

    await entered.wait()
    assert cancelled.is_set() is True
    assert send.await_args is not None
    assert send.await_args.args[0]["error"]["code"] == -32001


@pytest.mark.asyncio
async def test_native_login_receives_only_agent_hub_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = CodexCredentials(
        "database-access", "private-database-refresh", "account"
    )
    protocol = _Protocol(MagicMock())
    request = AsyncMock(return_value={"type": "chatgptAuthTokens"})
    protocol.request = request  # type: ignore[method-assign]
    ensure = AsyncMock(return_value=credentials)
    monkeypatch.setattr(native_runtime, "ensure_fresh_codex_credentials", ensure)

    await _login_with_agent_hub_auth(protocol)

    ensure.assert_awaited_once_with()
    assert request.await_args is not None
    method, params = request.await_args.args
    assert method == "account/login/start"
    assert params == {
        "type": "chatgptAuthTokens",
        "accessToken": "database-access",
        "chatgptAccountId": "account",
        "chatgptPlanType": None,
    }
    assert "private-database-refresh" not in json.dumps(params)


@pytest.mark.asyncio
async def test_native_login_rejects_unsupported_external_auth_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = _Protocol(MagicMock())
    protocol.request = AsyncMock(return_value={})  # type: ignore[method-assign]
    monkeypatch.setattr(
        native_runtime,
        "ensure_fresh_codex_credentials",
        AsyncMock(
            return_value=CodexCredentials(
                "database-access", "private-database-refresh", "account"
            )
        ),
    )

    with pytest.raises(
        native_runtime.NativeRuntimeError,
        match="does not support Agent Hub authentication",
    ):
        await _login_with_agent_hub_auth(protocol)


def _key(**changes: object) -> NativeRuntimeKey:
    values: dict[str, Any] = {
        "session_id": "session",
        "generation": 1,
        "client_id": "neri",
        "project_id": "neri",
        "role": "hunter",
        "controller_generation": "controller-1",
        "instruction_hash": "a" * 64,
        "tool_policy_hash": NATIVE_TOOL_POLICY_HASH,
        "model": "codex/gpt-daybreak-blue-latest",
        "reasoning_effort": "xhigh",
    }
    values.update(changes)
    return NativeRuntimeKey(**values)


def test_usage_prefers_last_turn_and_falls_back_to_cumulative_delta() -> None:
    first, total = _turn_usage(
        {
            "total": {"inputTokens": 100, "cachedInputTokens": 40, "outputTokens": 20},
            "last": {"inputTokens": 100, "cachedInputTokens": 40, "outputTokens": 20},
        },
        {},
    )
    second, _ = _turn_usage(
        {"total": {"inputTokens": 135, "cachedInputTokens": 65, "outputTokens": 28}},
        total,
    )

    assert (first.input_tokens, first.cache_read_tokens, first.output_tokens) == (100, 40, 20)
    assert (second.input_tokens, second.cache_read_tokens, second.output_tokens) == (35, 25, 8)
    assert first.known is True
    assert second.known is True


def test_cumulative_updates_keep_one_turn_baseline() -> None:
    baseline = {"input": 70, "cache": 0, "output": 0, "reasoning": 0}
    interim, _ = _turn_usage({"total": {"inputTokens": 100}}, baseline)
    final, _ = _turn_usage({"total": {"inputTokens": 120}}, baseline)

    assert interim.input_tokens == 30
    assert final.input_tokens == 50


@pytest.mark.asyncio
async def test_manager_reuses_one_runtime_for_snapshot_then_delta() -> None:
    manager = NativeRuntimeManager()
    key = _key()
    runtime = AsyncMock()
    runtime.key = key
    runtime.turn.side_effect = [
        NativeTurnObservation(
            answer_text='{"step":1}',
            thread_id="thread-1",
            turn_id="turn-1",
            observed_model="gpt-daybreak-blue-latest",
            usage=NativeTurnUsage(input_tokens=10, output_tokens=2, known=True),
            runtime="test",
        ),
        NativeTurnObservation(
            answer_text='{"step":2}',
            thread_id="thread-1",
            turn_id="turn-2",
            observed_model="gpt-daybreak-blue-latest",
            usage=NativeTurnUsage(input_tokens=4, output_tokens=2, known=True),
            runtime="test",
        ),
    ]
    start = AsyncMock(return_value=runtime)
    manager._start = start  # type: ignore[method-assign]

    first = await manager.execute(
        key,
        mode="snapshot",
        instructions="bounded role",
        prompt="full state",
        output_schema={"type": "object"},
        close_after=False,
    )
    second = await manager.execute(
        key,
        mode="delta",
        instructions="",
        prompt="new evidence only",
        output_schema={"type": "object"},
        close_after=True,
    )

    assert first.thread_id == second.thread_id == "thread-1"
    start.assert_awaited_once()
    assert runtime.turn.await_args_list[1].args[0] == "new evidence only"
    runtime.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_manager_never_reconstructs_a_missing_delta_runtime() -> None:
    manager = NativeRuntimeManager()
    start = AsyncMock()
    manager._start = start  # type: ignore[method-assign]

    with pytest.raises(NativeRuntimeLost):
        await manager.execute(
            _key(),
            mode="delta",
            instructions="",
            prompt="delta",
            output_schema=None,
            close_after=False,
        )

    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_cancellation_closes_retained_runtime() -> None:
    manager = NativeRuntimeManager()
    key = _key()
    entered = asyncio.Event()

    async def wait_forever(*_args: object) -> NativeTurnObservation:
        entered.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    runtime = AsyncMock()
    runtime.key = key
    runtime.turn.side_effect = wait_forever
    manager._runtimes[(key.session_id, key.generation)] = runtime
    task = asyncio.create_task(
        manager.execute(
            key,
            mode="delta",
            instructions="",
            prompt="new evidence",
            output_schema=None,
            close_after=False,
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    runtime.close.assert_awaited_once()
    assert manager._runtimes == {}
