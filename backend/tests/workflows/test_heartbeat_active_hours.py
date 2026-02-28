"""Tests for heartbeat active hours enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest


class TestActiveHoursEnforcement:
    """Verify heartbeat skips outside 9am-11pm ET."""

    @pytest.mark.asyncio
    async def test_skips_at_2am_et(self):
        """Heartbeat should not run at 2am Eastern."""
        from app.workflows.persona_heartbeat import _should_run

        # 2am ET = 7am UTC
        fake_utc = datetime(2026, 2, 27, 7, 0, 0, tzinfo=UTC)

        with (
            patch(
                "app.workflows.persona_heartbeat._get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            # Mock datetime.now to return our fixed time for both UTC and ET calls
            def fake_now(tz=None):
                if tz is None:
                    return fake_utc
                return fake_utc.astimezone(tz)

            mock_dt.now = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat

            should, interval = await _should_run()
            assert should is False
            assert interval == 60

    @pytest.mark.asyncio
    async def test_runs_at_2pm_et(self):
        """Heartbeat should run at 2pm Eastern (within active hours)."""
        from app.workflows.persona_heartbeat import _should_run

        # 2pm ET = 7pm UTC
        fake_utc = datetime(2026, 2, 27, 19, 0, 0, tzinfo=UTC)

        with (
            patch(
                "app.workflows.persona_heartbeat._get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            def fake_now(tz=None):
                if tz is None:
                    return fake_utc
                return fake_utc.astimezone(tz)

            mock_dt.now = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat

            mock_redis_client = AsyncMock()
            mock_redis_client.get.return_value = None
            mock_redis_client.close = AsyncMock()

            with patch("redis.asyncio.from_url", return_value=mock_redis_client):
                should, _interval = await _should_run()
                assert should is True

    @pytest.mark.asyncio
    async def test_skips_at_midnight_et(self):
        """Heartbeat should not run at midnight Eastern."""
        from app.workflows.persona_heartbeat import _should_run

        # midnight ET = 5am UTC
        fake_utc = datetime(2026, 2, 27, 5, 0, 0, tzinfo=UTC)

        with (
            patch(
                "app.workflows.persona_heartbeat._get_heartbeat_interval",
                new_callable=AsyncMock,
                return_value=(60, True),
            ),
            patch(
                "app.workflows.persona_heartbeat.datetime",
                wraps=datetime,
            ) as mock_dt,
        ):
            def fake_now(tz=None):
                if tz is None:
                    return fake_utc
                return fake_utc.astimezone(tz)

            mock_dt.now = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat

            should, _interval = await _should_run()
            assert should is False

    @pytest.mark.asyncio
    async def test_skips_when_not_onboarded(self):
        """Heartbeat should not run if onboarding is incomplete."""
        from app.workflows.persona_heartbeat import _should_run

        with patch(
            "app.workflows.persona_heartbeat._get_heartbeat_interval",
            new_callable=AsyncMock,
            return_value=(60, False),
        ):
            should, _interval = await _should_run()
            assert should is False

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Heartbeat should not run if interval is 0 (disabled)."""
        from app.workflows.persona_heartbeat import _should_run

        with patch(
            "app.workflows.persona_heartbeat._get_heartbeat_interval",
            new_callable=AsyncMock,
            return_value=(0, True),
        ):
            should, interval = await _should_run()
            assert should is False
            assert interval == 0
