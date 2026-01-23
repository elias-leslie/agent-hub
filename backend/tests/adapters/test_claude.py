"""Tests for Claude adapter (OAuth-only mode)."""

from unittest.mock import patch

import pytest

from app.adapters.base import Message
from app.adapters.claude import ClaudeAdapter


@pytest.fixture
def mock_cli_available():
    """Mock shutil.which to return Claude CLI path."""
    with patch("app.adapters.claude.shutil.which", return_value="/usr/local/bin/claude"):
        yield


@pytest.fixture
def mock_no_cli():
    """Mock shutil.which to return None (no Claude CLI)."""
    with patch("app.adapters.claude.shutil.which", return_value=None):
        yield


class TestClaudeAdapter:
    """Tests for ClaudeAdapter (OAuth-only)."""

    def test_init_with_cli(self, mock_cli_available):
        """Test initialization with Claude CLI available."""
        adapter = ClaudeAdapter()
        assert adapter.provider_name == "claude"
        assert adapter.auth_mode == "oauth"

    def test_init_no_cli_raises(self, mock_no_cli):
        """Test that missing Claude CLI raises ValueError."""
        with pytest.raises(ValueError, match="Claude adapter requires Claude CLI"):
            ClaudeAdapter()

    def test_health_check_with_cli(self, mock_cli_available):
        """Test health check with Claude CLI available."""
        adapter = ClaudeAdapter()
        # Synchronous test
        import asyncio

        result = asyncio.run(adapter.health_check())
        assert result is True

    def test_health_check_no_cli(self, mock_no_cli):
        """Test that initialization fails without CLI."""
        # Can't even create adapter without CLI, so this test just confirms that
        with pytest.raises(ValueError):
            ClaudeAdapter()
