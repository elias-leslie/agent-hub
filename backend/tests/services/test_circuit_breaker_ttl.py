from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.circuit_breaker import REDIS_CIRCUIT_TTL, CircuitBreakerManager


@pytest.mark.asyncio
async def test_trip_keeps_redis_state_for_full_cooldown() -> None:
    redis = AsyncMock()
    manager = CircuitBreakerManager()
    with patch("app.services.circuit_breaker.get_redis_client", new=AsyncMock(return_value=redis)):
        await manager.trip("gemini", cooldown_seconds=3600, error_signature="quota")

    ttl = redis.set.await_args.kwargs["ex"]
    assert ttl >= 3600


@pytest.mark.asyncio
async def test_untripped_state_uses_default_ttl() -> None:
    redis = AsyncMock()
    manager = CircuitBreakerManager()
    with patch("app.services.circuit_breaker.get_redis_client", new=AsyncMock(return_value=redis)):
        await manager.reset_circuit("gemini")

    assert redis.set.await_args.kwargs["ex"] == REDIS_CIRCUIT_TTL


@pytest.mark.asyncio
async def test_rate_limit_breaker_covers_providers_added_after_import() -> None:
    """The shared breaker is not built from an import-time provider list."""
    from app.services import agent_routing_completion

    with patch("app.services.circuit_breaker.get_redis_client", new=AsyncMock(return_value=None)):
        breaker = agent_routing_completion._RATE_LIMIT_BREAKER
        await breaker.trip("provider-added-later", cooldown_seconds=120, error_signature="429")
        try:
            remaining = await breaker.get_cooldown_remaining("provider-added-later")
        finally:
            await breaker.reset_circuit("provider-added-later")

    assert remaining is not None and remaining > 0
