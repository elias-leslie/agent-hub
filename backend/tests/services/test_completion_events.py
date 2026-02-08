"""Tests for completion event types and result storage."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.services.completion_events import (
    CompletionEventType,
    CompletionProgressEvent,
    store_task_result,
)


class TestCompletionProgressEvent:
    def test_serialization_roundtrip(self) -> None:
        event = CompletionProgressEvent(
            task_id="task-123",
            session_id="sess-456",
            event_type=CompletionEventType.STARTED,
            data={"turn": 1},
        )
        raw = event.to_json()
        restored = CompletionProgressEvent.from_json(raw)

        assert restored.task_id == "task-123"
        assert restored.session_id == "sess-456"
        assert restored.event_type == CompletionEventType.STARTED
        assert restored.data == {"turn": 1}
        assert restored.timestamp == event.timestamp

    def test_from_json_bytes(self) -> None:
        event = CompletionProgressEvent(
            task_id="t1",
            session_id="s1",
            event_type=CompletionEventType.COMPLETED,
        )
        raw_bytes = event.to_json().encode()
        restored = CompletionProgressEvent.from_json(raw_bytes)
        assert restored.event_type == CompletionEventType.COMPLETED

    def test_all_event_types_serialize(self) -> None:
        for evt_type in CompletionEventType:
            event = CompletionProgressEvent(
                task_id="t", session_id="s", event_type=evt_type
            )
            restored = CompletionProgressEvent.from_json(event.to_json())
            assert restored.event_type == evt_type


class TestStoreAndGetTaskResult:
    @patch("redis.Redis")
    @patch("app.config.settings")
    def test_store_task_result(self, mock_settings: MagicMock, mock_redis_cls: MagicMock) -> None:
        mock_settings.agent_hub_redis_url = "redis://localhost:6379/0"
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client

        result = {"content": "done", "status": "success"}
        store_task_result("task-42", result)

        mock_client.setex.assert_called_once()
        key, ttl, _value = mock_client.setex.call_args[0]
        assert key == "completion:result:task-42"
        assert ttl == 3600
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("redis.asyncio.Redis")
    @patch("app.config.settings")
    async def test_get_task_result_found(self, mock_settings: MagicMock, mock_async_redis_cls: MagicMock) -> None:
        import json

        from app.services.completion_events import get_task_result

        mock_settings.agent_hub_redis_url = "redis://localhost:6379/0"
        mock_client = MagicMock()

        async def mock_get(key: str) -> bytes:
            return json.dumps({"status": "success"}).encode()

        async def mock_close() -> None:
            pass

        mock_client.get = mock_get
        mock_client.close = mock_close
        mock_async_redis_cls.from_url.return_value = mock_client

        result = await get_task_result("task-42")
        assert result == {"status": "success"}

    @pytest.mark.asyncio
    @patch("redis.asyncio.Redis")
    @patch("app.config.settings")
    async def test_get_task_result_not_found(self, mock_settings: MagicMock, mock_async_redis_cls: MagicMock) -> None:
        from app.services.completion_events import get_task_result

        mock_settings.agent_hub_redis_url = "redis://localhost:6379/0"
        mock_client = MagicMock()

        async def mock_get(key: str) -> None:
            return None

        async def mock_close() -> None:
            pass

        mock_client.get = mock_get
        mock_client.close = mock_close
        mock_async_redis_cls.from_url.return_value = mock_client

        result = await get_task_result("nonexistent")
        assert result is None


class TestMapCompletionToSessionEvent:
    def test_maps_all_event_types(self) -> None:
        from app.services.events import (
            SessionEventType,
            _map_completion_to_session_event,
        )

        mappings = {
            "started": SessionEventType.SESSION_START,
            "completed": SessionEventType.COMPLETE,
            "failed": SessionEventType.ERROR,
            "cancelled": SessionEventType.ERROR,
            "tool_use": SessionEventType.TOOL_USE,
            "tool_result": SessionEventType.TOOL_USE,
            "turn_start": SessionEventType.MESSAGE,
            "progress": SessionEventType.MESSAGE,
        }

        for event_type_str, expected_session_type in mappings.items():
            event = _map_completion_to_session_event(event_type_str, "sess-1", {"info": "test"})
            assert event.event_type == expected_session_type, f"Failed for {event_type_str}"
            assert event.session_id == "sess-1"
            assert event.data == {"info": "test"}

    def test_unknown_type_defaults_to_message(self) -> None:
        from app.services.events import (
            SessionEventType,
            _map_completion_to_session_event,
        )

        event = _map_completion_to_session_event("unknown_type", "sess-1", {})
        assert event.event_type == SessionEventType.MESSAGE


class TestHatchetStreamBridgeLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_bridge(self) -> None:
        import app.services.events as events_mod
        from app.services.events import (
            start_hatchet_stream_bridge,
            stop_all_stream_bridges,
        )

        events_mod._stream_bridge_tasks.clear()

        with patch("app.services.events._hatchet_stream_bridge_loop") as mock_loop:
            async def fake_loop(task_id: str, workflow_run_id: str) -> None:
                await asyncio.sleep(100)

            mock_loop.side_effect = fake_loop

            await start_hatchet_stream_bridge("task-1", "run-1")
            assert "task-1" in events_mod._stream_bridge_tasks

            await stop_all_stream_bridges()
            assert len(events_mod._stream_bridge_tasks) == 0

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        import app.services.events as events_mod

        events_mod._stream_bridge_tasks.clear()

        with patch("app.services.events._hatchet_stream_bridge_loop") as mock_loop:
            async def fake_loop(task_id: str, workflow_run_id: str) -> None:
                await asyncio.sleep(100)

            mock_loop.side_effect = fake_loop

            await events_mod.start_hatchet_stream_bridge("task-1", "run-1")
            task1 = events_mod._stream_bridge_tasks.get("task-1")
            await events_mod.start_hatchet_stream_bridge("task-1", "run-1")
            task2 = events_mod._stream_bridge_tasks.get("task-1")
            assert task1 is task2

            await events_mod.stop_all_stream_bridges()
