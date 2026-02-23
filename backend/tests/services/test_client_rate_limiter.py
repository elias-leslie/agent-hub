"""Tests for per-client rate limiter service."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.client_rate_limiter import (
    check_client_rate_limit,
    get_client_rate_usage,
    record_client_tokens,
)


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Reset the module-level Redis singleton before each test."""
    import app.services.client_rate_limiter as mod

    mod._redis = None
    yield
    mod._redis = None


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    mock_client = AsyncMock()
    with patch("app.services.client_rate_limiter._get_redis", return_value=mock_client):
        yield mock_client


@pytest.mark.asyncio
async def test_check_rate_limit_under_rpm_allows(mock_redis):
    """Request under RPM limit should be allowed."""
    mock_redis.incr.return_value = 5  # 5th request this minute
    mock_redis.get.return_value = "0"  # no tokens used yet

    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=60, tpm_limit=100000)

    assert allowed is True
    assert reason is None
    mock_redis.incr.assert_called_once()


@pytest.mark.asyncio
async def test_check_rate_limit_rpm_exceeded_denies(mock_redis):
    """Request exceeding RPM limit should be denied."""
    mock_redis.incr.return_value = 61  # 61st request, limit is 60

    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=60, tpm_limit=None)

    assert allowed is False
    assert reason is not None
    assert "RPM" in reason
    assert "61" in reason
    assert "60" in reason


@pytest.mark.asyncio
async def test_check_rate_limit_tpm_exceeded_denies(mock_redis):
    """Request when TPM limit is already exceeded should be denied."""
    mock_redis.incr.return_value = 1  # RPM under limit
    mock_redis.get.return_value = "150000"  # tokens already over limit

    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=60, tpm_limit=100000)

    assert allowed is False
    assert reason is not None
    assert "TPM" in reason
    assert "150000" in reason


@pytest.mark.asyncio
async def test_null_limits_always_allows(mock_redis):
    """None limits should always allow the request (unlimited)."""
    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=None, tpm_limit=None)

    assert allowed is True
    assert reason is None
    # Should not touch Redis at all when limits are None
    mock_redis.incr.assert_not_called()
    mock_redis.get.assert_not_called()


@pytest.mark.asyncio
async def test_zero_limits_always_allows(mock_redis):
    """Zero limits should always allow the request (unlimited)."""
    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=0, tpm_limit=0)

    assert allowed is True
    assert reason is None
    # Should not touch Redis at all when limits are 0
    mock_redis.incr.assert_not_called()
    mock_redis.get.assert_not_called()


@pytest.mark.asyncio
async def test_redis_error_fails_open(mock_redis):
    """Redis error should fail-open (allow the request)."""
    mock_redis.incr.side_effect = ConnectionError("Redis unavailable")

    allowed, reason = await check_client_rate_limit("client-1", rpm_limit=60, tpm_limit=100000)

    assert allowed is True
    assert reason is None


@pytest.mark.asyncio
async def test_record_tokens_increments_counter(mock_redis):
    """record_client_tokens should increment the TPM counter."""
    mock_redis.incrby.return_value = 500

    await record_client_tokens("client-1", tokens=500)

    mock_redis.incrby.assert_called_once()
    args = mock_redis.incrby.call_args
    assert args[0][1] == 500  # second positional arg is the token count
    assert "rate_limit:tpm:client-1:" in args[0][0]


@pytest.mark.asyncio
async def test_record_tokens_sets_ttl_on_first_increment(mock_redis):
    """TTL should be set when the key is first created (new_total == tokens)."""
    mock_redis.incrby.return_value = 500  # first increment: total equals tokens

    await record_client_tokens("client-1", tokens=500)

    mock_redis.expire.assert_called_once()
    expire_args = mock_redis.expire.call_args
    assert expire_args[0][1] == 90  # _MINUTE_TTL


@pytest.mark.asyncio
async def test_record_tokens_skips_zero(mock_redis):
    """record_client_tokens should skip when tokens <= 0."""
    await record_client_tokens("client-1", tokens=0)
    await record_client_tokens("client-1", tokens=-5)

    mock_redis.incrby.assert_not_called()


@pytest.mark.asyncio
async def test_get_rate_usage_returns_values(mock_redis):
    """get_client_rate_usage should return current RPM and TPM counters."""
    mock_redis.get.side_effect = ["42", "9500"]  # rpm=42, tpm=9500

    usage = await get_client_rate_usage("client-1")

    assert usage == {"rpm_current": 42, "tpm_current": 9500}
    assert mock_redis.get.call_count == 2


@pytest.mark.asyncio
async def test_get_rate_usage_returns_zeros_on_missing_keys(mock_redis):
    """get_client_rate_usage should return zeros when keys don't exist."""
    mock_redis.get.side_effect = [None, None]

    usage = await get_client_rate_usage("client-1")

    assert usage == {"rpm_current": 0, "tpm_current": 0}


@pytest.mark.asyncio
async def test_get_rate_usage_redis_error_returns_zeros(mock_redis):
    """Redis error in get_client_rate_usage should return zeros."""
    mock_redis.get.side_effect = ConnectionError("Redis unavailable")

    usage = await get_client_rate_usage("client-1")

    assert usage == {"rpm_current": 0, "tpm_current": 0}


@pytest.mark.asyncio
async def test_independent_client_counters(mock_redis):
    """Different client_ids should use independent Redis keys."""
    call_keys = []

    async def capture_incr(key):
        call_keys.append(key)
        return 1

    mock_redis.incr.side_effect = capture_incr
    mock_redis.get.return_value = "0"

    await check_client_rate_limit("client-a", rpm_limit=60, tpm_limit=100000)
    await check_client_rate_limit("client-b", rpm_limit=60, tpm_limit=100000)

    # Verify different keys were used for each client
    assert len(call_keys) == 2
    assert "client-a" in call_keys[0]
    assert "client-b" in call_keys[1]
    assert call_keys[0] != call_keys[1]


@pytest.mark.asyncio
async def test_rpm_sets_ttl_on_first_request(mock_redis):
    """TTL should be set on the RPM key when it's first created."""
    mock_redis.incr.return_value = 1  # first request
    mock_redis.get.return_value = "0"

    await check_client_rate_limit("client-1", rpm_limit=60, tpm_limit=None)

    mock_redis.expire.assert_called_once()
    expire_args = mock_redis.expire.call_args
    assert expire_args[0][1] == 90  # _MINUTE_TTL


@pytest.mark.asyncio
async def test_record_tokens_redis_error_fails_open(mock_redis):
    """Redis error in record_client_tokens should not raise."""
    mock_redis.incrby.side_effect = ConnectionError("Redis unavailable")

    # Should not raise
    await record_client_tokens("client-1", tokens=500)
