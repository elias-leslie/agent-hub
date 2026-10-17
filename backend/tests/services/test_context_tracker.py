"""Tests for context tracking service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.context_tracker import (
    CONTEXT_CRITICAL_THRESHOLD,
    CONTEXT_HIGH_THRESHOLD,
    CONTEXT_WARNING_THRESHOLD,
    ContextUsage,
    calculate_context_usage,
    check_context_before_request,
    format_budget_message,
    get_session_token_totals,
    log_token_usage,
    should_emit_warning,
)
from app.services.token_counter import get_context_limit
from tests.model_ids import CLAUDE_HAIKU, CLAUDE_SONNET, DEFAULT_GEMINI_MODEL

_LIMIT = get_context_limit(CLAUDE_HAIKU)


def _pct(percent: int) -> int:
    return _LIMIT * percent // 100


class TestLogTokenUsage:
    """Tests for log_token_usage."""

    @pytest.mark.asyncio
    async def test_logs_token_usage(self):
        """Test that token usage is logged to database."""
        mock_db = AsyncMock()

        await log_token_usage(
            db=mock_db,
            session_id="test-session-123",
            model=CLAUDE_SONNET,
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.015,
        )

        # Verify CostLog was added
        mock_db.add.assert_called_once()
        cost_log = mock_db.add.call_args[0][0]
        assert cost_log.session_id == "test-session-123"
        assert cost_log.model == CLAUDE_SONNET
        assert cost_log.input_tokens == 1000
        assert cost_log.output_tokens == 500
        # Claude runs on the subscription: $0 cash, list price kept as API-equivalent.
        assert cost_log.cost_usd == 0.0
        assert cost_log.billing_mode == "subscription"
        assert cost_log.api_equiv_usd == pytest.approx((1000 * 2.0 + 500 * 10.0) / 1e6)


class TestGetSessionTokenTotals:
    """Tests for get_session_token_totals."""

    @pytest.mark.asyncio
    async def test_returns_totals(self):
        """Test that token totals are aggregated correctly."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = (5000, 2500)
        mock_db.execute.return_value = mock_result

        input_total, output_total = await get_session_token_totals(mock_db, "test-session-123")

        assert input_total == 5000
        assert output_total == 2500

    @pytest.mark.asyncio
    async def test_returns_zero_for_no_logs(self):
        """Test returns 0,0 when no cost logs exist."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.one.return_value = (0, 0)
        mock_db.execute.return_value = mock_result

        input_total, output_total = await get_session_token_totals(mock_db, "new-session")

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
        mock_totals.one.return_value = (_pct(25), 20000)

        # Latest context query
        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = _pct(25)

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(mock_db, "test-session-123", CLAUDE_HAIKU)

        assert usage.used_tokens == _pct(25)
        assert usage.limit_tokens == _LIMIT
        assert usage.percent_used == 25.0
        assert usage.remaining_tokens == _LIMIT - _pct(25)
        assert usage.warning is None  # 25% is below warning threshold

    @pytest.mark.asyncio
    async def test_warning_at_50_percent(self):
        """Test note emitted at 50% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (_pct(50), 40000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = _pct(50)

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(mock_db, "test-session", CLAUDE_HAIKU)

        assert usage.percent_used == 50.0
        assert usage.warning is not None
        assert "50.0%" in usage.warning
        assert "Note:" in usage.warning

    @pytest.mark.asyncio
    async def test_warning_at_75_percent(self):
        """Test warning emitted at 75% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (_pct(75), 60000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = _pct(75)

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(mock_db, "test-session", CLAUDE_HAIKU)

        assert usage.percent_used == 75.0
        assert usage.warning is not None
        assert "WARNING:" in usage.warning

    @pytest.mark.asyncio
    async def test_critical_warning_at_90_percent(self):
        """Test critical warning at 90% capacity."""
        mock_db = AsyncMock()

        mock_totals = MagicMock()
        mock_totals.one.return_value = (_pct(90), 70000)

        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = _pct(90)

        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(mock_db, "test-session", CLAUDE_HAIKU)

        assert usage.percent_used == 90.0
        assert usage.warning is not None
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

        usage = await calculate_context_usage(mock_db, "new-session", CLAUDE_HAIKU)

        assert usage.used_tokens == 0
        assert usage.percent_used == 0.0
        assert usage.remaining_tokens == _LIMIT
        assert usage.measured is False

    @pytest.mark.asyncio
    async def test_recorded_zero_context_is_measured(self):
        mock_db = AsyncMock()
        mock_totals = MagicMock()
        mock_totals.one.return_value = (0, 0)
        mock_latest = MagicMock()
        mock_latest.scalar_one_or_none.return_value = 0
        mock_db.execute.side_effect = [mock_totals, mock_latest]

        usage = await calculate_context_usage(mock_db, "zero-session", CLAUDE_HAIKU)

        assert usage.used_tokens == 0
        assert usage.measured is True


class TestCheckContextBeforeRequest:
    """Tests for check_context_before_request."""

    @pytest.mark.asyncio
    async def test_allows_request_under_limit(self):
        """Test request allowed when under context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", CLAUDE_HAIKU, _pct(25)
        )

        assert can_proceed is True
        assert usage.used_tokens == _pct(25)
        assert usage.percent_used == 25.0

    @pytest.mark.asyncio
    async def test_blocks_request_over_limit(self):
        """Test request blocked when exceeding context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", CLAUDE_HAIKU, _pct(125)
        )

        assert can_proceed is False
        assert usage.warning is not None
        assert "BLOCKED:" in usage.warning

    @pytest.mark.asyncio
    async def test_warning_near_limit(self):
        """Test warning when request approaches limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", CLAUDE_HAIKU, _pct(90)
        )

        assert can_proceed is True
        assert usage.percent_used == 90.0
        assert usage.warning is not None
        assert "CRITICAL:" in usage.warning

    @pytest.mark.asyncio
    async def test_gemini_larger_context(self):
        """Test Gemini model has larger context limit."""
        mock_db = AsyncMock()

        can_proceed, usage = await check_context_before_request(
            mock_db, "test-session", DEFAULT_GEMINI_MODEL, 500000
        )

        assert can_proceed is True
        assert usage.limit_tokens == 1_048_576
        assert usage.percent_used == 47.68


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


class TestFormatBudgetMessage:
    """Tests for format_budget_message."""

    def test_no_message_below_50_percent(self):
        assert format_budget_message(49_000, 200_000) is None

    def test_tracking_at_50_percent(self):
        msg = format_budget_message(100_000, 200_000)
        assert msg is not None
        assert "100K/200K" in msg
        assert "tracking" in msg

    def test_warning_at_75_percent(self):
        msg = format_budget_message(150_000, 200_000)
        assert msg is not None
        assert "wrapping up" in msg

    def test_critical_at_90_percent(self):
        msg = format_budget_message(180_000, 200_000)
        assert msg is not None
        assert "CRITICAL" in msg
        assert "handoff" in msg

    def test_emitted_thresholds_prevents_repeat(self):
        emitted: set[int] = set()
        msg1 = format_budget_message(100_000, 200_000, emitted_thresholds=emitted)
        assert msg1 is not None
        msg2 = format_budget_message(110_000, 200_000, emitted_thresholds=emitted)
        assert msg2 is None  # 50% already emitted

    def test_emitted_thresholds_allows_escalation(self):
        emitted: set[int] = set()
        format_budget_message(100_000, 200_000, emitted_thresholds=emitted)
        msg = format_budget_message(150_000, 200_000, emitted_thresholds=emitted)
        assert msg is not None  # 75% is a new threshold
        assert "wrapping up" in msg

    def test_zero_limit_returns_none(self):
        assert format_budget_message(100_000, 0) is None
