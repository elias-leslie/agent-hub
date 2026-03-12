"""Tests for bounded closeout-audit behavior in multi-turn execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.adapters.base import Message
from app.api.complete.finish_reason_handler import handle_finish_reason


@pytest.mark.asyncio
async def test_handle_finish_reason_injects_one_shot_closeout_audit_for_persona_heartbeat() -> None:
    messages_for_adapter: list[Message] = []
    messages_dict: list[dict[str, str]] = []
    progress_log: list = []
    state = {"closeout_audit_used": False}

    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=3,
        max_turns=10,
        result=SimpleNamespace(content="HEARTBEAT_OK — Completed checks."),
        messages_for_adapter=messages_for_adapter,
        messages_dict=messages_dict,
        progress_log=progress_log,
        progress_callback=AsyncMock(),
        state=state,
        agent_slug="persona",
        task_type="heartbeat",
    )

    assert should_break is False
    assert status == "success"
    assert error is None
    assert state["closeout_audit_used"] is True
    assert messages_for_adapter[-2].role == "assistant"
    assert messages_for_adapter[-1].role == "user"
    assert "final completion audit" in messages_for_adapter[-1].content.lower()
    assert messages_dict[-2]["role"] == "assistant"
    assert messages_dict[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_handle_finish_reason_does_not_repeat_closeout_audit() -> None:
    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=4,
        max_turns=10,
        result=SimpleNamespace(content="HEARTBEAT_OK — Completed checks."),
        messages_for_adapter=[],
        messages_dict=[],
        progress_log=[],
        progress_callback=AsyncMock(),
        state={"closeout_audit_used": True},
        agent_slug="persona",
        task_type="heartbeat",
    )

    assert should_break is True
    assert status == "success"
    assert error is None


@pytest.mark.asyncio
async def test_handle_finish_reason_skips_closeout_audit_for_non_persona_session() -> None:
    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=2,
        max_turns=10,
        result=SimpleNamespace(content="done"),
        messages_for_adapter=[],
        messages_dict=[],
        progress_log=[],
        progress_callback=AsyncMock(),
        state={"closeout_audit_used": False},
        agent_slug="refactor",
        task_type="task",
    )

    assert should_break is True
    assert status == "success"
    assert error is None


@pytest.mark.asyncio
async def test_handle_finish_reason_retries_empty_end_turn_once() -> None:
    messages_for_adapter: list[Message] = []
    messages_dict: list[dict[str, str]] = []
    progress_log: list = []
    state = {"closeout_audit_used": False, "closeout_recovery_used": False}

    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=2,
        max_turns=10,
        result=SimpleNamespace(content=""),
        messages_for_adapter=messages_for_adapter,
        messages_dict=messages_dict,
        progress_log=progress_log,
        progress_callback=AsyncMock(),
        state=state,
        agent_slug="memory-curator",
        task_type="task",
    )

    assert should_break is False
    assert status == "success"
    assert error is None
    assert state["closeout_recovery_used"] is True
    assert messages_for_adapter[-2].role == "assistant"
    assert messages_for_adapter[-1].role == "user"
    assert "final user-facing response" in messages_for_adapter[-1].content.lower()
    assert messages_dict[-2]["role"] == "assistant"
    assert messages_dict[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_handle_finish_reason_retries_empty_end_turn_in_grace_window() -> None:
    messages_for_adapter: list[Message] = []
    messages_dict: list[dict[str, str]] = []
    progress_log: list = []
    state = {"closeout_audit_used": False, "closeout_recovery_used": False}

    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=10,
        max_turns=10,
        hard_cap=11,
        result=SimpleNamespace(content=""),
        messages_for_adapter=messages_for_adapter,
        messages_dict=messages_dict,
        progress_log=progress_log,
        progress_callback=AsyncMock(),
        state=state,
        agent_slug="memory-curator",
        task_type="task",
    )

    assert should_break is False
    assert status == "success"
    assert error is None
    assert state["closeout_recovery_used"] is True
    assert messages_for_adapter[-1].role == "user"


@pytest.mark.asyncio
async def test_handle_finish_reason_does_not_repeat_empty_end_turn_retry() -> None:
    should_break, status, error = await handle_finish_reason(
        finish_reason="end_turn",
        turn=3,
        max_turns=10,
        result=SimpleNamespace(content=""),
        messages_for_adapter=[],
        messages_dict=[],
        progress_log=[],
        progress_callback=AsyncMock(),
        state={"closeout_audit_used": False, "closeout_recovery_used": True},
        agent_slug="memory-curator",
        task_type="task",
    )

    assert should_break is True
    assert status == "success"
    assert error is None
