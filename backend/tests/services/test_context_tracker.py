"""Tests for context tracking service."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.context_tracker import (
    ContextUsage,
    calculate_context_usage,
    check_context_before_request,
    get_session_token_totals,
    log_token_usage,
    should_emit_warning,
    CONTEXT_WARNING_THRESHOLD,
    CONTEXT_HIGH_THRESHOLD,
    CONTEXT_CRITICAL_THRESHOLD,
)


class TestLogTokenUsage:
    """Tests for log_token_usage."""

    @pytest.mark.asyncio
    async def test_logs_token_usage(self):
        """Test that token usage is logged to database."""
        mock_db = AsyncMock()

        await log_token_usage(
            db=mock_db,
            session_id="test-session-123",
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.015,
        )

        # Verify CostLog was added
        mock_db.add.assert_called_once()
        cost_log = mock_db.add.call_args[0][0]
        assert cost_log.session_id == "test-session-123"
        assert cost_log.model == "claude-sonnet-4-5"
        assert cost_log.input_tokens == 1000
        assert cost_log.output_tokens == 500
        assert cost_log.cost_usd == 0.015


class TestGetSessionTokenTotals:
    """Tests for get_session_token_totals."""

    @pytest.mark.asyncio
    async def test_returns_totals(self):
        """Test that token totals are aggregated correctly."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = (5000, 2500)
        mock_db.execute.return_value = mock_result

        input_total, output_total = await get_session_token_totals(
            mock_db, "test-session-123"
        )

        assert input_total == 5000
        assert output_total == 2500

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_logs(self):
        """Test returns 0,0 when no cost logs exist."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = (0, 0)
        mock_db.execute.return_value = mock_result

        input_total, output_total = await get_session_token_totals(
            mock_db, "new-session"
        )

        assert input_total == 0
        assert output_total == 0


class TestCalculateContextUsage:
    """Tests for calculate_context_usage."""

    @pytest.mark.asyncio
    async def test_calculates_usage_correctly(self):
        """Test context usage calculation."""
        mock_db = AsyncMock()

        # Token totals query
        mock_totals = MagicMock()
        mock_totals.one.return_value = (50000, 20000)

        # Latest context query
        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = 50000

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(
            mock_db, "test-session-123", "claude-sonnet-4-5"
        )

        assert usage.used_tokens == 50000
        assert usage.limit_tokens == 200000  # Claude context limit
        assert usage.percent_used == 25.0
        assert usage.remaining_tokens == 150000
        assert usage.warning is None  # 25% is below warning threshold

    @pytest.mark.asyncio
    async def test_warning_at_50_percent(self):
        """Test note emitted at 50% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (100000, 40000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = 100000

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(
            mock_db, "test-session", "claude-sonnet-4-5"
        )

        assert usage.percent_used == 50.0
        assert "50.0%" in usage.warning
        assert "Note:" in usage.warning

    @pytest.mark.asyncio
    async def test_warning_at_75_percent(self):
        """Test warning emitted at 75% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (150000, 60000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = 150000

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(
            mock_db, "test-session", "claude-sonnet-4-5"
        )

        assert usage.percent_used == 75.0
        assert "WARNING:" in usage.warning

    @pytest.mark.asyncio
    async def test_critical_warning_at_90_percent(self):
        """Test critical warning at 90% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (180000, 70000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = 180000

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(
            mock_db, "test-session", "claude-sonnet-4-5"
        )

        assert usage.percent_used == 90.0
        assert "CRITICAL:" in usage.warning

    @pytest.mark.asyncio
    async def test_no_context_returns_zero(self):
        """Test new session with no context logs."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (0, 0)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(
            mock_db, "new-session", "claude-sonnet-4-5"
        )

        assert usage.used_tokens == 0
        assert usage.percent_used == 0.0
        assert usage.remaining_tokens == 200000


class TestCheckContextBeforeRequest:
    """Tests for check_context_before_request."""

    @pytest.mark.asyncio
    async def test_allows_request_under_limit(self):
        """Test request allowed when under context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", "claude-sonnet-4-5", 50000
        )

        assert can_proceed is True
        assert usage.used_tokens == 50000
        assert usage.percent_used == 25.0

    @pytest.mark.asyncio
    async def test_blocks_request_over_limit(self):
        """Test request blocked when exceeding context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", "claude-sonnet-4-5", 250000
        )

        assert can_proceed is False
        assert "BLOCKED:" in usage.warning

    @pytest.mark.asyncio
    async def test_warning_near_limit(self):
        """Test warning when request approaches limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", "claude-sonnet-4-5", 180000
        )

        assert can_proceed is True
        assert usage.percent_used == 90.0
        assert "CRITICAL:" in usage.warning

    @pytest.mark.asyncio
    async def test_gemini_larger_context(self):
        """Test Gemini model has larger context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", "gemini-2.0-flash", 500000
        )

        assert can_proceed is True
        assert usage.limit_tokens == 1000000
        assert usage.percent_used == 50.0


class TestShouldEmitWarning:
    """Tests for should_emit_warning."""

    def test_no_warning_below_threshold(self):
        """Test no warning emitted below threshold."""
        assert should_emit_warning(50.0) is False
        assert should_emit_warning(74.9) is False

    def test_warning_at_threshold(self):
        """Test warning emitted at threshold."""
        assert should_emit_warning(75.0) is True
        assert should_emit_warning(80.0) is True
        assert should_emit_warning(95.0) is True


class TestContextUsageDataclass:
    """Tests for ContextUsage dataclass."""

    def test_creates_usage_with_warning(self):
        """Test ContextUsage with warning."""
        usage = ContextUsage(
            used_tokens=180000,
            limit_tokens=200000,
            percent_used=90.0,
            remaining_tokens=20000,
            warning="CRITICAL: at 90%",
        )

        assert usage.used_tokens == 180000
        assert usage.warning == "CRITICAL: at 90%"

    def test_creates_usage_without_warning(self):
        """Test ContextUsage without warning."""
        usage = ContextUsage(
            used_tokens=50000,
            limit_tokens=200000,
            percent_used=25.0,
            remaining_tokens=150000,
        )

        assert usage.warning is None


class TestThresholdConstants:
    """Tests for threshold constants."""

    def test_thresholds_are_ordered(self):
        """Test thresholds are in correct order."""
        assert CONTEXT_WARNING_THRESHOLD < CONTEXT_HIGH_THRESHOLD
        assert CONTEXT_HIGH_THRESHOLD < CONTEXT_CRITICAL_THRESHOLD

    def test_threshold_values(self):
        """Test threshold values are sensible."""
        assert CONTEXT_WARNING_THRESHOLD == 50
        assert CONTEXT_HIGH_THRESHOLD == 75
        assert CONTEXT_CRITICAL_THRESHOLD == 90
