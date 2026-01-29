"""
Request queue for handling dual-provider failures.

Queues requests when all providers are unavailable, then retries them
when providers recover.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from app.services.health_prober import HealthEvent, HealthProber, ProviderHealth

logger = logging.getLogger(__name__)


@dataclass
class QueuedRequest:
    """A request waiting in the queue."""

    id: str
    created_at: float
    execute_fn: Callable[[], Coroutine[Any, Any, Any]]
    future: asyncio.Future[Any]
    timeout_at: float


@dataclass
class RequestQueueConfig:
    """Configuration for request queue."""

    max_queue_size: int = 100
    request_timeout_seconds: float = 60.0
    retry_interval_seconds: float = 5.0


@dataclass
class RequestQueueStats:
    """Statistics for the request queue."""

    current_size: int = 0
    total_queued: int = 0
    total_succeeded: int = 0
    total_failed: int = 0
    total_timeout: int = 0
    total_rejected: int = 0


class QueueFullError(Exception):
    """Raised when the request queue is full."""

    def __init__(self, retry_after: float = 30.0):
        super().__init__("Request queue is full")
        self.retry_after = retry_after


@dataclass
class RequestQueue:
    """
    Request queue for handling dual-provider failures.

    When all providers are unavailable, queues incoming requests and
    retries them when providers recover. Provides configurable queue
    size and timeout.
    """

    config: RequestQueueConfig = field(default_factory=RequestQueueConfig)
    health_prober: HealthProber | None = None
    _queue: asyncio.Queue[QueuedRequest] | None = None
    _stats: RequestQueueStats = field(default_factory=RequestQueueStats)
    _running: bool = False
    _processor_task: asyncio.Task[None] | None = None
    _request_counter: int = 0

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue(maxsize=self.config.max_queue_size)
        self._stats = RequestQueueStats()

    def _on_provider_recovered(
        self, event: HealthEvent, provider: str, health: ProviderHealth
    ) -> None:
        """Handle provider recovery event."""
        if event == HealthEvent.PROVIDER_RECOVERED:
            logger.info(f"Provider {provider} recovered, processing queued requests")
            if not self._running and self._queue and not self._queue.empty():
                self.start_processing()

    def register_with_prober(self, prober: HealthProber) -> None:
        """Register with health prober to receive recovery events."""
        self.health_prober = prober
        prober.add_event_handler(self._on_provider_recovered)

    def unregister_from_prober(self) -> None:
        """Unregister from health prober."""
        if self.health_prober:
            self.health_prober.remove_event_handler(self._on_provider_recovered)
            self.health_prober = None

    async def enqueue(
        self,
        request_fn: Callable[[], Coroutine[Any, Any, Any]],
        timeout: float | None = None,
    ) -> Any:
        """
        Enqueue a request for later execution.

        Args:
            request_fn: Async function to execute when providers available
            timeout: Optional timeout override (defaults to config timeout)

        Returns:
            Result from the request function when executed

        Raises:
            QueueFullError: If queue is at capacity
            asyncio.TimeoutError: If request times out waiting in queue
        """
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=self.config.max_queue_size)

        if self._queue.full():
            self._stats.total_rejected += 1
            raise QueueFullError(retry_after=self.config.retry_interval_seconds)

        self._request_counter += 1
        request_id = f"req-{self._request_counter}"
        effective_timeout = timeout or self.config.request_timeout_seconds

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        request = QueuedRequest(
            id=request_id,
            created_at=time.time(),
            execute_fn=request_fn,
            future=future,
            timeout_at=time.time() + effective_timeout,
        )

        try:
            self._queue.put_nowait(request)
            self._stats.total_queued += 1
            self._stats.current_size = self._queue.qsize()
            logger.info(f"Request {request_id} queued (size: {self._stats.current_size})")
        except asyncio.QueueFull as err:
            self._stats.total_rejected += 1
            raise QueueFullError(retry_after=self.config.retry_interval_seconds) from err

        try:
            return await asyncio.wait_for(future, timeout=effective_timeout)
        except TimeoutError:
            self._stats.total_timeout += 1
            logger.warning(f"Request {request_id} timed out after {effective_timeout}s")
            raise

    async def _process_queue(self) -> None:
        """Process queued requests when providers are available."""
        if self._queue is None:
            return

        while self._running and not self._queue.empty():
            if self.health_prober and not self.health_prober.get_available_providers():
                logger.debug("No providers available, waiting")
                await asyncio.sleep(self.config.retry_interval_seconds)
                continue

            try:
                request: QueuedRequest = self._queue.get_nowait()
                self._stats.current_size = self._queue.qsize()
            except asyncio.QueueEmpty:
                break

            if request.future.done():
                continue

            if time.time() > request.timeout_at:
                if not request.future.done():
                    request.future.set_exception(TimeoutError(f"Request {request.id} timed out"))
                    self._stats.total_timeout += 1
                continue

            try:
                result = await request.execute_fn()
                if not request.future.done():
                    request.future.set_result(result)
                    self._stats.total_succeeded += 1
                    logger.info(f"Request {request.id} succeeded")
            except Exception as e:
                if not request.future.done():
                    request.future.set_exception(e)
                    self._stats.total_failed += 1
                    logger.warning(f"Request {request.id} failed: {e}")

        self._running = False
        self._processor_task = None

    def start_processing(self) -> None:
        """Start processing queued requests."""
        if self._running:
            return
        self._running = True
        self._processor_task = asyncio.create_task(self._process_queue())
        logger.info("Request queue processor started")

    async def stop_processing(self) -> None:
        """Stop processing queued requests."""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processor_task
            self._processor_task = None
        logger.info("Request queue processor stopped")

    def get_stats(self) -> RequestQueueStats:
        """Get queue statistics."""
        if self._queue:
            self._stats.current_size = self._queue.qsize()
        return self._stats

    def get_queue_size(self) -> int:
        """Get current queue size."""
        return self._queue.qsize() if self._queue else 0

    def get_queue_position(self, request_id: str) -> int | None:
        """Get position of a request in queue (for UI display)."""
        if self._queue is None:
            return None
        for position, item in enumerate(list(self._queue._queue), start=1):  # type: ignore[attr-defined]
            if item.id == request_id:
                return position
        return None

    def get_estimated_wait_time(self) -> float:
        """Estimate wait time based on queue size and retry interval."""
        queue_size = self.get_queue_size()
        return queue_size * self.config.retry_interval_seconds


# Global singleton
_request_queue: RequestQueue | None = None


def get_request_queue() -> RequestQueue:
    """Get the global request queue instance."""
    global _request_queue
    if _request_queue is None:
        _request_queue = RequestQueue()
    return _request_queue


def init_request_queue(
    config: RequestQueueConfig | None = None,
    health_prober: HealthProber | None = None,
) -> RequestQueue:
    """Initialize the global request queue."""
    global _request_queue
    if _request_queue is not None:
        return _request_queue
    _request_queue = RequestQueue(config=config or RequestQueueConfig())
    if health_prober:
        _request_queue.register_with_prober(health_prober)
    return _request_queue


async def shutdown_request_queue() -> None:
    """Shutdown the global request queue."""
    global _request_queue
    if _request_queue is not None:
        _request_queue.unregister_from_prober()
        await _request_queue.stop_processing()
        _request_queue = None
