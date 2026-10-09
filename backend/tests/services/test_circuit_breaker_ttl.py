from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.circuit_breaker import REDIS_CIRCUIT_TTL, CircuitBreakerManager


@pytest.mark.asyncio
async def test_trip_keeps_redis_state_for_full_cooldown() -> None:
    redis = AsyncMock()
    manager = CircuitBreakerManager(["gemini"])
    with patch("app.services.circuit_breaker.get_redis_client", new=AsyncMock(return_value=redis)):
        await manager.trip("gemini", cooldown_seconds=3600, error_signature="quota")

    ttl = redis.set.await_args.kwargs["ex"]
    assert ttl >= 3600


@pytest.mark.asyncio
async def test_untripped_state_uses_default_ttl() -> None:
    redis = AsyncMock()
    manager = CircuitBreakerManager(["gemini"])
    with patch("app.services.circuit_breaker.get_redis_client", new=AsyncMock(return_value=redis)):
        await manager.reset_circuit("gemini")

    assert redis.set.await_args.kwargs["ex"] == REDIS_CIRCUIT_TTL
