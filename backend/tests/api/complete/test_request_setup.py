"""Tests for completion request setup memory injection behavior."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.complete.request_setup import inject_memory


class _FakeContext:
    def __init__(self) -> None:
        self.mandates = ["m1"]
        self.guardrails = ["g1"]
        self.reference = ["r1"]

    def get_loaded_uuids(self) -> list[str]:
        return ["11111111-1111-1111-1111-111111111111"]


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        use_memory=True,
        memory_group_id="project:agent-hub",
        task_type=None,
        phase=None,
        project_id="agent-hub",
        external_id=None,
        current_branch=None,
    )


def _resolved_agent(memory_config: dict[str, object] | None) -> SimpleNamespace:
    return SimpleNamespace(agent=SimpleNamespace(memory_config=memory_config, slug="coder"))


@pytest.mark.asyncio
async def test_inject_memory_skips_when_injection_disabled_flag() -> None:
    request = _request()
    messages = [{"role": "user", "content": "hi"}]

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
    ) as mock_inject:
        result_messages, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=messages,
            session_id="s1",
            resolved_agent=_resolved_agent({"injection_enabled": False}),
            db=None,
        )

    assert result_messages == messages
    assert injected_count == 0
    assert loaded == []
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_inject_memory_skips_when_enabled_false() -> None:
    request = _request()

    with patch(
        "app.api.complete.request_setup.inject_progressive_context",
        new_callable=AsyncMock,
    ) as mock_inject:
        _, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"enabled": False}),
            db=None,
        )

    assert injected_count == 0
    assert loaded == []
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_inject_memory_tracks_loaded_batch_when_enabled() -> None:
    request = _request()
    db = AsyncMock()

    with (
        patch(
            "app.api.complete.request_setup.parse_memory_group_id",
            return_value=("project", "agent-hub"),
        ),
        patch(
            "app.api.complete.request_setup.inject_progressive_context",
            new_callable=AsyncMock,
            return_value=([{"role": "system", "content": "mem"}], _FakeContext()),
        ) as mock_inject,
        patch(
            "app.api.complete.request_setup.track_loaded_batch",
            new_callable=AsyncMock,
        ) as mock_track,
        patch(
            "app.api.complete.request_setup.store_memory_inject_event",
            new_callable=AsyncMock,
        ) as mock_store,
    ):
        result_messages, injected_count, loaded = await inject_memory(
            request=request,
            messages_dict=[{"role": "user", "content": "hi"}],
            session_id="s1",
            resolved_agent=_resolved_agent({"include_mandates": True}),
            db=db,
        )

    assert result_messages[0]["role"] == "system"
    assert injected_count == 3
    assert loaded == ["11111111-1111-1111-1111-111111111111"]
    mock_inject.assert_awaited_once()
    mock_track.assert_awaited_once_with(["11111111-1111-1111-1111-111111111111"])
    mock_store.assert_awaited_once()

