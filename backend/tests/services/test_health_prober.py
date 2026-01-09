"""Tests for health prober service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.health_prober import (
    HealthEvent,
    HealthProber,
    HealthProberConfig,
    ProviderHealth,
    ProviderState,
    get_health_prober,
    init_health_prober,
    shutdown_health_prober,
)


class TestProviderHealth:
    """Tests for ProviderHealth dataclass."""

    def test_availability_no_checks(self):
        """Test availability with no checks returns 1.0."""
        health = ProviderHealth(name="test")
        assert health.availability == 1.0
        assert health.error_rate == 0.0

    def test_availability_all_success(self):
        """Test availability with all successes."""
        health = ProviderHealth(name="test", success_count=10, error_count=0)
        assert health.availability == 1.0
        assert health.error_rate == 0.0

    def test_availability_all_errors(self):
        """Test availability with all errors."""
        health = ProviderHealth(name="test", success_count=0, error_count=10)
        assert health.availability == 0.0
        assert health.error_rate == 1.0

    def test_availability_mixed(self):
        """Test availability with mixed results."""
        health = ProviderHealth(name="test", success_count=7, error_count=3)
        assert health.availability == pytest.approx(0.7)
        assert health.error_rate == pytest.approx(0.3)

    def test_default_state(self):
        """Test default state is unknown."""
        health = ProviderHealth(name="test")
        assert health.state == ProviderState.UNKNOWN


class TestProviderState:
    """Tests for ProviderState enum."""

    def test_state_values(self):
        """Test state enum values."""
        assert ProviderState.HEALTHY.value == "healthy"
        assert ProviderState.DEGRADED.value == "degraded"
        assert ProviderState.DOWN.value == "down"
        assert ProviderState.UNKNOWN.value == "unknown"


class TestHealthProber:
    """Tests for HealthProber class."""

    @pytest.fixture
    def mock_adapters(self):
        """Create mock adapters for testing."""
        claude_adapter = MagicMock()
        claude_adapter.health_check = AsyncMock(return_value=True)

        gemini_adapter = MagicMock()
        gemini_adapter.health_check = AsyncMock(return_value=True)

        return {"claude": claude_adapter, "gemini": gemini_adapter}

    @pytest.fixture
    def prober(self, mock_adapters):
        """Create a prober with mock adapters (bypass __post_init__)."""
        config = HealthProberConfig(
            probe_interval_seconds=0.1,
            degraded_threshold=2,
            down_threshold=3,
        )
        # Create prober without calling __post_init__ by using object.__new__
        prober = object.__new__(HealthProber)
        prober.config = config
        prober._adapters = mock_adapters
        prober._providers = {name: ProviderHealth(name=name) for name in mock_adapters}
        prober._event_handlers = []
        prober._running = False
        prober._probe_task = None
        return prober

    @pytest.mark.asyncio
    async def test_probe_healthy(self, prober, mock_adapters):
        """Test successful health probe."""
        await prober._probe_provider("claude")

        health = prober.get_health("claude")
        assert health is not None
        assert health.state == ProviderState.HEALTHY
        assert health.success_count == 1
        assert health.error_count == 0
        assert health.consecutive_failures == 0
        assert health.last_check > 0

    @pytest.mark.asyncio
    async def test_probe_failure_updates_state(self, prober, mock_adapters):
        """Test that failures update state correctly."""
        mock_adapters["claude"].health_check = AsyncMock(side_effect=Exception("Connection error"))

        # First failure
        await prober._probe_provider("claude")
        health = prober.get_health("claude")
        assert health.consecutive_failures == 1
        assert health.state == ProviderState.UNKNOWN

        # Second failure -> degraded
        await prober._probe_provider("claude")
        health = prober.get_health("claude")
        assert health.consecutive_failures == 2
        assert health.state == ProviderState.DEGRADED

        # Third failure -> down
        await prober._probe_provider("claude")
        health = prober.get_health("claude")
        assert health.consecutive_failures == 3
        assert health.state == ProviderState.DOWN

    @pytest.mark.asyncio
    async def test_emit_events_on_state_change(self, prober, mock_adapters):
        """Test that events are emitted on state changes."""
        events_received = []

        def event_handler(event, provider, health):
            events_received.append((event, provider))

        prober.add_event_handler(event_handler)

        # Start in healthy state
        prober.get_health("claude").state = ProviderState.HEALTHY

        mock_adapters["claude"].health_check = AsyncMock(side_effect=Exception("Connection error"))

        # Failures to trigger degraded (from healthy)
        await prober._probe_provider("claude")
        await prober._probe_provider("claude")
        assert (HealthEvent.PROVIDER_DEGRADED, "claude") in events_received

        # More failures to trigger down
        await prober._probe_provider("claude")
        assert (HealthEvent.PROVIDER_DOWN, "claude") in events_received

    @pytest.mark.asyncio
    async def test_recovery_event(self, prober, mock_adapters):
        """Test that recovery event is emitted."""
        events_received = []

        def event_handler(event, provider, health):
            events_received.append((event, provider))

        prober.add_event_handler(event_handler)

        # Set provider to down state
        health = prober.get_health("claude")
        health.state = ProviderState.DOWN
        health.consecutive_failures = 3

        # Successful probe should trigger recovery
        mock_adapters["claude"].health_check = AsyncMock(return_value=True)
        await prober._probe_provider("claude")
        await prober._probe_provider("claude")

        assert (HealthEvent.PROVIDER_RECOVERED, "claude") in events_received

    @pytest.mark.asyncio
    async def test_is_provider_available(self, prober, mock_adapters):
        """Test is_provider_available method."""
        health = prober.get_health("claude")

        health.state = ProviderState.HEALTHY
        assert prober.is_provider_available("claude") is True

        health.state = ProviderState.DEGRADED
        assert prober.is_provider_available("claude") is True

        health.state = ProviderState.DOWN
        assert prober.is_provider_available("claude") is False

        health.state = ProviderState.UNKNOWN
        assert prober.is_provider_available("claude") is False

    @pytest.mark.asyncio
    async def test_get_available_providers(self, prober, mock_adapters):
        """Test get_available_providers method."""
        prober.get_health("claude").state = ProviderState.HEALTHY
        prober.get_health("gemini").state = ProviderState.DOWN

        available = prober.get_available_providers()
        assert "claude" in available
        assert "gemini" not in available

    @pytest.mark.asyncio
    async def test_probe_now_single(self, prober, mock_adapters):
        """Test immediate probe for single provider."""
        await prober.probe_now("claude")

        health = prober.get_health("claude")
        assert health.success_count == 1

        gemini_health = prober.get_health("gemini")
        assert gemini_health.success_count == 0

    @pytest.mark.asyncio
    async def test_probe_now_all(self, prober, mock_adapters):
        """Test immediate probe for all providers."""
        await prober.probe_now()

        assert prober.get_health("claude").success_count == 1
        assert prober.get_health("gemini").success_count == 1

    @pytest.mark.asyncio
    async def test_start_stop(self, prober, mock_adapters):
        """Test start and stop background probing."""
        prober.start()
        assert prober._running is True
        assert prober._probe_task is not None

        await asyncio.sleep(0.15)

        await prober.stop()
        assert prober._running is False
        assert prober._probe_task is None

    @pytest.mark.asyncio
    async def test_latency_tracking(self, prober, mock_adapters):
        """Test that latency is tracked."""
        await prober._probe_provider("claude")

        health = prober.get_health("claude")
        assert health.latency_ms > 0

    @pytest.mark.asyncio
    async def test_high_latency_degrades_state(self, prober, mock_adapters):
        """Test that high latency marks provider as degraded."""

        async def slow_health_check():
            await asyncio.sleep(0.01)
            return True

        mock_adapters["claude"].health_check = slow_health_check
        prober.config.latency_degraded_ms = 5

        await prober._probe_provider("claude")

        health = prober.get_health("claude")
        assert health.state == ProviderState.DEGRADED

    def test_add_remove_event_handler(self, prober, mock_adapters):
        """Test adding and removing event handlers."""

        def handler(event, provider, health):
            pass

        prober.add_event_handler(handler)
        assert handler in prober._event_handlers

        prober.remove_event_handler(handler)
        assert handler not in prober._event_handlers

    @pytest.mark.asyncio
    async def test_error_recorded(self, prober, mock_adapters):
        """Test that error messages are recorded."""
        mock_adapters["claude"].health_check = AsyncMock(
            side_effect=Exception("Test error message")
        )

        await prober._probe_provider("claude")

        health = prober.get_health("claude")
        assert health.last_error is not None
        assert "Test error message" in health.last_error


class TestGlobalProber:
    """Tests for global prober functions."""

    @pytest.fixture(autouse=True)
    def reset_global_prober(self):
        """Reset global prober before and after each test."""
        import app.services.health_prober as hp_module

        hp_module._health_prober = None
        yield
        hp_module._health_prober = None

    @pytest.mark.asyncio
    async def test_init_and_shutdown(self):
        """Test init and shutdown of global prober."""
        with (
            patch("app.services.health_prober.ClaudeAdapter"),
            patch("app.services.health_prober.GeminiAdapter"),
        ):
            prober = init_health_prober()
            assert prober is not None
            assert prober._running is True

            await shutdown_health_prober()

            from app.services.health_prober import _health_prober

            assert _health_prober is None

    def test_get_health_prober_creates_instance(self):
        """Test that get_health_prober creates instance if needed."""
        import app.services.health_prober as hp_module

        hp_module._health_prober = None

        with (
            patch("app.services.health_prober.ClaudeAdapter"),
            patch("app.services.health_prober.GeminiAdapter"),
        ):
            prober = get_health_prober()
            assert prober is not None

        hp_module._health_prober = None
