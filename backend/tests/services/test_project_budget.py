"""Tests for per-project cost budget service."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.project_budget import (
    check_project_budget,
    get_project_budget_usage,
    invalidate_budget_cache,
    record_project_cost,
)


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Reset the module-level Redis singleton before each test."""
    import app.services.project_budget as mod

    mod._redis = None
    yield
    mod._redis = None


@pytest.fixture
def mock_redis():
    """Create a mock async Redis client."""
    mock_client = AsyncMock()
    with patch("app.services.project_budget._get_redis", return_value=mock_client):
        yield mock_client


@dataclass
class _FakePerm:
    """Minimal fake ProjectPermission for testing."""

    project_id: str = "test-project-1"
    daily_cost_budget_usd: float | None = 10.0
    monthly_cost_budget_usd: float | None = 100.0
    budget_alert_threshold: float = 0.8


def _make_mock_db(perm: _FakePerm | None = None):
    """Create a mock AsyncSession that returns the given perm."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = perm
    mock_db.execute.return_value = mock_result
    return mock_db


# ---------------------------------------------------------------------------
# check_project_budget — under limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_passes_under_daily_limit(mock_redis):
    """Budget check should pass when daily usage is under the limit."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=None)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["5.0", "0"]  # daily=5.0, monthly=0

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.reason is None
    assert result.daily_usage_usd == 5.0
    assert result.daily_limit_usd == 10.0


@pytest.mark.asyncio
async def test_budget_check_passes_under_monthly_limit(mock_redis):
    """Budget check should pass when monthly usage is under the limit."""
    perm = _FakePerm(daily_cost_budget_usd=None, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["0", "50.0"]  # daily=0, monthly=50.0

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.reason is None
    assert result.monthly_usage_usd == 50.0
    assert result.monthly_limit_usd == 100.0


# ---------------------------------------------------------------------------
# check_project_budget — limits exceeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_fails_daily_limit_exceeded(mock_redis):
    """Budget check should fail when daily limit is exceeded."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["10.5", "50.0"]  # daily exceeded

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is False
    assert result.reason is not None
    assert "daily" in result.reason
    assert result.alert_level == "critical"


@pytest.mark.asyncio
async def test_budget_check_fails_monthly_limit_exceeded(mock_redis):
    """Budget check should fail when monthly limit is exceeded."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["5.0", "100.0"]  # monthly at limit

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is False
    assert result.reason is not None
    assert "monthly" in result.reason
    assert result.alert_level == "critical"


# ---------------------------------------------------------------------------
# check_project_budget — null limits (unlimited)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_null_limits_always_passes(mock_redis):
    """Budget check with null limits (unlimited) should always pass."""
    perm = _FakePerm(daily_cost_budget_usd=None, monthly_cost_budget_usd=None)
    mock_db = _make_mock_db(perm)

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.reason is None
    assert result.daily_limit_usd is None
    assert result.monthly_limit_usd is None
    # Should not touch Redis when limits are None
    mock_redis.get.assert_not_called()


# ---------------------------------------------------------------------------
# check_project_budget — fail-closed on errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_fail_closed_on_redis_error(mock_redis):
    """Budget check should fail-closed on Redis errors."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ConnectionError("Redis unavailable")

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is False
    assert result.reason is not None
    assert "budget check error" in result.reason


@pytest.mark.asyncio
async def test_budget_check_fail_closed_on_db_error(mock_redis):
    """Budget check should fail-closed on database errors."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("DB connection failed")

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is False
    assert result.reason is not None
    assert "budget check error" in result.reason


@pytest.mark.asyncio
async def test_budget_check_fail_closed_on_unknown_project(mock_redis):
    """Budget check should fail-closed when project is not found."""
    mock_db = _make_mock_db(None)  # No permission record

    result = await check_project_budget("test-project-unknown", db=mock_db)

    assert result.allowed is False
    assert result.reason is not None
    assert "no permission record" in result.reason


# ---------------------------------------------------------------------------
# record_project_cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_cost_increments_both_counters(mock_redis):
    """record_project_cost should increment both daily and monthly counters."""
    mock_redis.incrbyfloat.side_effect = [0.05, 0.05]  # first increment

    await record_project_cost("test-project-1", 0.05)

    assert mock_redis.incrbyfloat.call_count == 2
    # Check both calls used the correct cost
    for call in mock_redis.incrbyfloat.call_args_list:
        assert call[0][1] == 0.05


@pytest.mark.asyncio
async def test_record_cost_sets_ttl_on_first_increment(mock_redis):
    """TTL should be set when the key is first created (new_total approx equals cost)."""
    mock_redis.incrbyfloat.side_effect = [0.05, 0.05]  # first increment

    await record_project_cost("test-project-1", 0.05)

    # Should set TTL twice (once for daily key, once for monthly key)
    assert mock_redis.expire.call_count == 2
    ttls = [call[0][1] for call in mock_redis.expire.call_args_list]
    assert 90000 in ttls  # _DAY_TTL
    assert 2764800 in ttls  # _MONTH_TTL


@pytest.mark.asyncio
async def test_record_cost_no_ttl_on_subsequent_increment(mock_redis):
    """TTL should not be set on subsequent increments."""
    mock_redis.incrbyfloat.side_effect = [1.05, 50.05]  # not first increment

    await record_project_cost("test-project-1", 0.05)

    # Should not set TTL since totals are not approximately equal to cost
    mock_redis.expire.assert_not_called()


@pytest.mark.asyncio
async def test_record_cost_skips_zero(mock_redis):
    """record_project_cost should skip when cost_usd <= 0."""
    await record_project_cost("test-project-1", 0.0)

    mock_redis.incrbyfloat.assert_not_called()


@pytest.mark.asyncio
async def test_record_cost_skips_negative(mock_redis):
    """record_project_cost should skip when cost_usd is negative."""
    await record_project_cost("test-project-1", -0.5)

    mock_redis.incrbyfloat.assert_not_called()


@pytest.mark.asyncio
async def test_record_cost_redis_error_fails_silently(mock_redis):
    """Redis error in record_project_cost should not raise."""
    mock_redis.incrbyfloat.side_effect = ConnectionError("Redis unavailable")

    # Should not raise
    await record_project_cost("test-project-1", 0.05)


# ---------------------------------------------------------------------------
# Alert levels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_level_none_below_threshold(mock_redis):
    """Alert level should be None when usage is below the threshold."""
    perm = _FakePerm(
        daily_cost_budget_usd=10.0,
        monthly_cost_budget_usd=100.0,
        budget_alert_threshold=0.8,
    )
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["5.0", "50.0"]  # 50% daily, 50% monthly

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.alert_level is None


@pytest.mark.asyncio
async def test_alert_level_warning_at_threshold(mock_redis):
    """Alert level should be 'warning' when usage reaches the threshold."""
    perm = _FakePerm(
        daily_cost_budget_usd=10.0,
        monthly_cost_budget_usd=100.0,
        budget_alert_threshold=0.8,
    )
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["8.5", "50.0"]  # 85% daily, 50% monthly

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.alert_level == "warning"


@pytest.mark.asyncio
async def test_alert_level_critical_at_95_percent(mock_redis):
    """Alert level should be 'critical' when usage reaches 95%."""
    perm = _FakePerm(
        daily_cost_budget_usd=10.0,
        monthly_cost_budget_usd=100.0,
        budget_alert_threshold=0.8,
    )
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["9.6", "50.0"]  # 96% daily, 50% monthly

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.alert_level == "critical"


@pytest.mark.asyncio
async def test_alert_level_monthly_triggers_warning(mock_redis):
    """Alert level should be 'warning' when monthly usage reaches the threshold."""
    perm = _FakePerm(
        daily_cost_budget_usd=10.0,
        monthly_cost_budget_usd=100.0,
        budget_alert_threshold=0.8,
    )
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["1.0", "85.0"]  # 10% daily, 85% monthly

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
    assert result.alert_level == "warning"


# ---------------------------------------------------------------------------
# get_project_budget_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_budget_usage_returns_correct_values(mock_redis):
    """get_project_budget_usage should return correct usage and limits."""
    perm = _FakePerm(
        daily_cost_budget_usd=10.0,
        monthly_cost_budget_usd=100.0,
        budget_alert_threshold=0.8,
    )
    mock_redis.get.side_effect = ["3.5", "45.0"]

    with patch("app.db.async_session") as mock_session_ctx:
        mock_db = _make_mock_db(perm)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        usage = await get_project_budget_usage("test-project-1")

    assert usage["project_id"] == "test-project-1"
    assert usage["daily"]["used"] == 3.5
    assert usage["daily"]["limit"] == 10.0
    assert usage["daily"]["remaining"] == 6.5
    assert usage["monthly"]["used"] == 45.0
    assert usage["monthly"]["limit"] == 100.0
    assert usage["monthly"]["remaining"] == 55.0
    assert usage["alert_level"] is None


@pytest.mark.asyncio
async def test_get_budget_usage_unlimited_project(mock_redis):
    """get_project_budget_usage should handle unlimited budgets."""
    perm = _FakePerm(
        daily_cost_budget_usd=None,
        monthly_cost_budget_usd=None,
        budget_alert_threshold=0.8,
    )
    mock_redis.get.side_effect = ["3.5", "45.0"]

    with patch("app.db.async_session") as mock_session_ctx:
        mock_db = _make_mock_db(perm)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        usage = await get_project_budget_usage("test-project-1")

    assert usage["daily"]["limit"] is None
    assert usage["daily"]["remaining"] is None
    assert usage["monthly"]["limit"] is None
    assert usage["monthly"]["remaining"] is None


@pytest.mark.asyncio
async def test_get_budget_usage_error_returns_zeros(mock_redis):
    """get_project_budget_usage should return zeros on error."""
    with patch("app.db.async_session") as mock_session_ctx:
        mock_session_ctx.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB error")
        )
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        usage = await get_project_budget_usage("test-project-1")

    assert usage["project_id"] == "test-project-1"
    assert usage["daily"]["used"] == 0.0
    assert usage["monthly"]["used"] == 0.0
    assert usage["alert_level"] is None


# ---------------------------------------------------------------------------
# invalidate_budget_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_budget_cache_is_noop(mock_redis):
    """invalidate_budget_cache is a no-op (budget limits come from DB, not Redis cache)."""
    await invalidate_budget_cache("test-project-1")

    # Should NOT touch Redis — the keys are cost accumulators, not a cache
    mock_redis.delete.assert_not_called()
    mock_redis.get.assert_not_called()


# ---------------------------------------------------------------------------
# check_project_budget — uses async_session when db is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_uses_async_session_when_db_is_none(mock_redis):
    """check_project_budget should use async_session when no db is provided."""
    perm = _FakePerm(daily_cost_budget_usd=None, monthly_cost_budget_usd=None)

    with patch("app.db.async_session") as mock_session_ctx:
        mock_db = _make_mock_db(perm)
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await check_project_budget("test-project-1", db=None)

    assert result.allowed is True
    mock_session_ctx.assert_called_once()


# ---------------------------------------------------------------------------
# check_project_budget — exact boundary cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_check_fails_at_exact_daily_limit(mock_redis):
    """Budget check should fail when daily usage exactly equals the limit."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["10.0", "50.0"]  # exactly at daily limit

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is False
    assert "daily" in result.reason


@pytest.mark.asyncio
async def test_budget_check_passes_just_under_daily_limit(mock_redis):
    """Budget check should pass when daily usage is just under the limit."""
    perm = _FakePerm(daily_cost_budget_usd=10.0, monthly_cost_budget_usd=100.0)
    mock_db = _make_mock_db(perm)
    mock_redis.get.side_effect = ["9.9999", "50.0"]  # just under daily limit

    result = await check_project_budget("test-project-1", db=mock_db)

    assert result.allowed is True
