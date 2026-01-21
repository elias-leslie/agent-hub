"""Tests for API key authentication service.

Focus on datetime comparison to prevent TypeError regressions.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.api_key_auth import validate_api_key


class FakeAPIKey:
    """Fake APIKey model for testing."""

    def __init__(
        self,
        is_active: int = 1,
        expires_at: datetime | None = None,
    ):
        self.is_active = is_active
        self.expires_at = expires_at


@pytest.fixture
def mock_db():
    """Create mock async database session."""
    db = AsyncMock()
    return db


def _setup_mock_db(mock_db: AsyncMock, key_record: FakeAPIKey | None) -> None:
    """Configure mock db to return given key record."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = key_record
    mock_db.execute.return_value = mock_result


@pytest.mark.asyncio
async def test_valid_key_with_future_expiration(mock_db):
    """Test case 1: Valid key with future expires_at passes."""
    future_time = datetime.now(UTC) + timedelta(hours=1)
    key_record = FakeAPIKey(is_active=1, expires_at=future_time)
    _setup_mock_db(mock_db, key_record)

    result = await validate_api_key(mock_db, "sk-ah-test-key")
    assert result is key_record


@pytest.mark.asyncio
async def test_expired_key_returns_none(mock_db):
    """Test case 2: Expired key with past expires_at returns None."""
    past_time = datetime.now(UTC) - timedelta(hours=1)
    key_record = FakeAPIKey(is_active=1, expires_at=past_time)
    _setup_mock_db(mock_db, key_record)

    result = await validate_api_key(mock_db, "sk-ah-test-key")
    assert result is None


@pytest.mark.asyncio
async def test_key_with_no_expiration_passes(mock_db):
    """Test case 3: Key with no expires_at (None) passes."""
    key_record = FakeAPIKey(is_active=1, expires_at=None)
    _setup_mock_db(mock_db, key_record)

    result = await validate_api_key(mock_db, "sk-ah-test-key")
    assert result is key_record


@pytest.mark.asyncio
async def test_no_typeerror_on_datetime_comparison(mock_db):
    """Test case 4: Ensure no TypeError when comparing datetimes.

    This regression test verifies that timezone-aware datetimes
    can be compared without TypeError after TIMESTAMPTZ migration.
    """
    # Timezone-aware datetime (simulating TIMESTAMPTZ from database)
    aware_time = datetime.now(UTC) - timedelta(minutes=5)
    key_record = FakeAPIKey(is_active=1, expires_at=aware_time)
    _setup_mock_db(mock_db, key_record)

    # Should not raise TypeError
    result = await validate_api_key(mock_db, "sk-ah-test-key")
    assert result is None  # Expired


@pytest.mark.asyncio
async def test_revoked_key_returns_none(mock_db):
    """Revoked key (is_active=0) returns None regardless of expiration."""
    future_time = datetime.now(UTC) + timedelta(hours=1)
    key_record = FakeAPIKey(is_active=0, expires_at=future_time)
    _setup_mock_db(mock_db, key_record)

    result = await validate_api_key(mock_db, "sk-ah-test-key")
    assert result is None
