"""Tests for completion event channel (Redis pub/sub + result storage)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.completion_events import (
    CompletionEventPublisher,
    CompletionEventType,
    CompletionProgressEvent,
    get_channel_name,
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


class TestGetChannelName:
    def test_channel_name_format(self) -> None:
        assert get_channel_name("abc-123") == "completion:progress:abc-123"


class TestCompletionEventPublisher:
    @patch("app.services.completion_events.CompletionEventPublisher._get_redis")
    def test_publish_calls_redis(self, mock_get_redis: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        publisher = CompletionEventPublisher("task-1", "sess-1")
        publisher.publish(CompletionEventType.STARTED, {"info": "starting"})

        mock_redis.publish.assert_called_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == "completion:progress:task-1"
        restored = CompletionProgressEvent.from_json(payload)
        assert restored.event_type == CompletionEventType.STARTED
        assert restored.data == {"info": "starting"}

    @patch("app.services.completion_events.CompletionEventPublisher._get_redis")
    def test_publish_swallows_redis_errors(self, mock_get_redis: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        mock_get_redis.return_value = mock_redis

        publisher = CompletionEventPublisher("task-1", "sess-1")
        publisher.publish(CompletionEventType.FAILED)

    @patch("app.services.completion_events.CompletionEventPublisher._get_redis")
    def test_close_cleans_up(self, mock_get_redis: MagicMock) -> None:
        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis

        publisher = CompletionEventPublisher("task-1", "sess-1")
        publisher._redis = mock_redis
        publisher.close()

        mock_redis.close.assert_called_once()
        assert publisher._redis is None

    def test_close_without_redis_is_noop(self) -> None:
        publisher = CompletionEventPublisher("task-1", "sess-1")
        publisher.close()


class TestStoreAndGetTaskResult:
    @patch("redis.Redis")
    @patch("app.config.settings")
    def test_store_task_result(self, mock_settings: MagicMock, mock_redis_cls: MagicMock) -> None:
        mock_settings.celery_broker_url = "redis://localhost:6379/0"
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

        mock_settings.celery_broker_url = "redis://localhost:6379/0"
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

        mock_settings.celery_broker_url = "redis://localhost:6379/0"
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
