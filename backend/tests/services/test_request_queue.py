"""Tests for request queue service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.health_prober import HealthEvent, ProviderHealth, ProviderState
from app.services.request_queue import (
    QueuedRequest,
    QueueFullError,
    RequestQueue,
    RequestQueueConfig,
    RequestQueueStats,
    get_request_queue,
    init_request_queue,
    shutdown_request_queue,
)


class TestQueueFullError:
    """Tests for QueueFullError."""

    def test_error_with_retry_after(self):
        """Test error includes retry after value."""
        error = QueueFullError(retry_after=45.0)
        assert error.retry_after == 45.0
        assert "queue is full" in str(error).lower()


class TestRequestQueueStats:
    """Tests for RequestQueueStats."""

    def test_default_values(self):
        """Test default statistics values."""
        stats = RequestQueueStats()
        assert stats.current_size == 0
        assert stats.total_queued == 0
        assert stats.total_succeeded == 0
        assert stats.total_failed == 0
        assert stats.total_timeout == 0
        assert stats.total_rejected == 0


class TestRequestQueue:
    """Tests for RequestQueue class."""

    @pytest.fixture
    def queue(self):
        """Create a request queue for testing."""
        config = RequestQueueConfig(
            max_queue_size=5,
            request_timeout_seconds=2.0,
            retry_interval_seconds=0.1,
        )
        return RequestQueue(config=config)

    @pytest.fixture
    def mock_prober(self):
        """Create a mock health prober."""
        prober = MagicMock()
        prober.get_available_providers = MagicMock(return_value=["claude"])
        prober.add_event_handler = MagicMock()
        prober.remove_event_handler = MagicMock()
        return prober

    @pytest.mark.asyncio
    async def test_enqueue_and_process(self, queue, mock_prober):
        """Test basic enqueue and process flow."""
        queue.register_with_prober(mock_prober)

        async def request_fn():
            return "result"

        queue.start_processing()
        result = await queue.enqueue(request_fn)

        assert result == "result"
        stats = queue.get_stats()
        assert stats.total_queued == 1
        assert stats.total_succeeded == 1

        await queue.stop_processing()

    @pytest.mark.asyncio
    async def test_queue_full_error(self, queue):
        """Test that queue full raises error."""
        futures = []

        async def slow_request():
            await asyncio.sleep(10)
            return "result"

        for i in range(5):
            try:
                task = asyncio.create_task(queue.enqueue(slow_request, timeout=10))
                futures.append(task)
            except QueueFullError:
                pass

        await asyncio.sleep(0.05)

        with pytest.raises(QueueFullError) as exc_info:
            await queue.enqueue(slow_request)

        assert exc_info.value.retry_after > 0

        for f in futures:
            f.cancel()

    @pytest.mark.asyncio
    async def test_request_timeout(self, queue, mock_prober):
        """Test that requests timeout correctly."""
        mock_prober.get_available_providers = MagicMock(return_value=[])
        queue.register_with_prober(mock_prober)

        async def request_fn():
            return "result"

        config = RequestQueueConfig(
            max_queue_size=5,
            request_timeout_seconds=0.1,
            retry_interval_seconds=0.5,
        )
        queue.config = config

        with pytest.raises(asyncio.TimeoutError):
            await queue.enqueue(request_fn, timeout=0.1)

    @pytest.mark.asyncio
    async def test_retry_on_recovery(self, queue, mock_prober):
        """Test that queued requests are processed on provider recovery."""
        available = []
        mock_prober.get_available_providers = MagicMock(side_effect=lambda: available)
        queue.register_with_prober(mock_prober)

        results = []

        async def request_fn():
            results.append("executed")
            return "result"

        enqueue_task = asyncio.create_task(queue.enqueue(request_fn, timeout=5.0))

        await asyncio.sleep(0.05)

        available.append("claude")
        queue.start_processing()

        result = await enqueue_task
        assert result == "result"
        assert "executed" in results

        await queue.stop_processing()

    @pytest.mark.asyncio
    async def test_multiple_requests_queued(self, queue, mock_prober):
        """Test multiple requests are queued and processed."""
        mock_prober.get_available_providers = MagicMock(return_value=["claude"])
        queue.register_with_prober(mock_prober)

        results = []

        def make_request_factory(n):
            async def make_request():
                results.append(n)
                return n
            return make_request

        tasks = []
        for i in range(3):
            task = asyncio.create_task(queue.enqueue(make_request_factory(i), timeout=5.0))
            tasks.append(task)
            await asyncio.sleep(0.01)

        queue.start_processing()

        await asyncio.gather(*tasks)

        assert len(results) == 3
        stats = queue.get_stats()
        assert stats.total_succeeded == 3

        await queue.stop_processing()

    @pytest.mark.asyncio
    async def test_failed_request_stats(self, queue, mock_prober):
        """Test that failed requests update stats."""
        mock_prober.get_available_providers = MagicMock(return_value=["claude"])
        queue.register_with_prober(mock_prober)

        async def failing_request():
            raise ValueError("Test error")

        queue.start_processing()

        with pytest.raises(ValueError):
            await queue.enqueue(failing_request)

        stats = queue.get_stats()
        assert stats.total_failed == 1

        await queue.stop_processing()

    def test_get_queue_size(self, queue):
        """Test get_queue_size method."""
        assert queue.get_queue_size() == 0

    def test_get_estimated_wait_time(self, queue):
        """Test estimated wait time calculation."""
        assert queue.get_estimated_wait_time() == 0.0

    @pytest.mark.asyncio
    async def test_start_stop_processing(self, queue):
        """Test start and stop processing."""
        queue.start_processing()
        assert queue._running is True

        await queue.stop_processing()
        assert queue._running is False

    def test_register_unregister_prober(self, queue, mock_prober):
        """Test registering and unregistering with health prober."""
        queue.register_with_prober(mock_prober)
        assert queue.health_prober == mock_prober
        mock_prober.add_event_handler.assert_called_once()

        queue.unregister_from_prober()
        assert queue.health_prober is None
        mock_prober.remove_event_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_event_triggers_processing(self, queue, mock_prober):
        """Test that provider recovery event triggers queue processing."""
        mock_prober.get_available_providers = MagicMock(return_value=["claude"])
        queue.register_with_prober(mock_prober)

        async def request_fn():
            return "result"

        task = asyncio.create_task(queue.enqueue(request_fn, timeout=5.0))
        await asyncio.sleep(0.05)

        health = ProviderHealth(name="claude", state=ProviderState.HEALTHY)
        queue._on_provider_recovered(HealthEvent.PROVIDER_RECOVERED, "claude", health)

        result = await task
        assert result == "result"

        await queue.stop_processing()


class TestGlobalQueue:
    """Tests for global queue functions."""

    @pytest.mark.asyncio
    async def test_init_and_shutdown(self):
        """Test init and shutdown of global queue."""
        import app.services.request_queue as rq_module

        rq_module._request_queue = None

        queue = init_request_queue()
        assert queue is not None

        await shutdown_request_queue()
        assert rq_module._request_queue is None

    def test_get_request_queue_creates_instance(self):
        """Test that get_request_queue creates instance if needed."""
        import app.services.request_queue as rq_module

        rq_module._request_queue = None

        queue = get_request_queue()
        assert queue is not None

        rq_module._request_queue = None

    @pytest.mark.asyncio
    async def test_init_with_config(self):
        """Test init with custom config."""
        import app.services.request_queue as rq_module

        rq_module._request_queue = None

        config = RequestQueueConfig(max_queue_size=50)
        queue = init_request_queue(config=config)

        assert queue.config.max_queue_size == 50

        await shutdown_request_queue()
