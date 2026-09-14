from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.native_continuation_runtime import (
    NATIVE_TOOL_POLICY_HASH,
    NativeRuntimeKey,
    NativeRuntimeLost,
    NativeRuntimeManager,
    NativeTurnObservation,
    NativeTurnUsage,
    _turn_usage,
)


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
