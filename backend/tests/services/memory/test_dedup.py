"""Tests for dedup module."""

from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.dedup import (
    add_content_hash_to_episode,
    content_hash,
    find_exact_duplicate,
    is_duplicate,
    normalize_content,
)


class TestNormalizeContent:
    """Tests for normalize_content function."""

    def test_trims_whitespace(self):
        """Test that leading/trailing whitespace is trimmed."""
        assert normalize_content("  hello  ") == "hello"

    def test_collapses_multiple_spaces(self):
        """Test that multiple spaces are collapsed to single space."""
        assert normalize_content("hello    world") == "hello world"

    def test_collapses_newlines(self):
        """Test that newlines are collapsed to spaces."""
        assert normalize_content("hello\n\nworld") == "hello world"

    def test_lowercases(self):
        """Test that content is lowercased."""
        assert normalize_content("HELLO World") == "hello world"

    def test_complex_normalization(self):
        """Test complex whitespace normalization."""
        content = "  Hello   World\n\t\nTest  "
        assert normalize_content(content) == "hello world test"


class TestContentHash:
    """Tests for content_hash function."""

    def test_content_hash_returns_hex_digest(self):
        """Test that hash returns hex string."""
        result = content_hash("test content")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 hex length

    def test_consistent_hashing(self):
        """Test that same content produces same hash."""
        hash1 = content_hash("hello world")
        hash2 = content_hash("hello world")
        assert hash1 == hash2

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        hash1 = content_hash("content a")
        hash2 = content_hash("content b")
        assert hash1 != hash2

    def test_normalization_applied(self):
        """Test that normalization is applied before hashing."""
        hash1 = content_hash("Hello World")
        hash2 = content_hash("hello   world")
        assert hash1 == hash2

    def test_whitespace_variants_same_hash(self):
        """Test that whitespace variants produce same hash."""
        variants = [
            "Python uses 4-space indentation.",
            "  Python uses 4-space indentation.  ",
            "Python  uses   4-space  indentation.",
            "PYTHON USES 4-SPACE INDENTATION.",
        ]
        hashes = [content_hash(v) for v in variants]
        # All should be the same after normalization
        assert len(set(hashes)) == 1


class TestIsDuplicate:
    """Tests for is_duplicate function."""

    def test_matching_content(self):
        """Test that matching content is detected."""
        content = "Test pattern"
        existing_hash = content_hash(content)
        assert is_duplicate(content, existing_hash) is True

    def test_non_matching_content(self):
        """Test that non-matching content is not duplicate."""
        existing_hash = content_hash("original content")
        assert is_duplicate("different content", existing_hash) is False

    def test_normalized_match(self):
        """Test that normalized variants match."""
        original_hash = content_hash("Hello World")
        assert is_duplicate("hello   world", original_hash) is True


class TestFindExactDuplicate:
    """Tests for find_exact_duplicate async function."""

    @pytest.mark.asyncio
    async def test_no_duplicates_found(self):
        """Test when no duplicates exist."""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=[])

        with patch(
            "app.services.memory.service.get_memory_service",
            return_value=mock_service,
        ):
            result = await find_exact_duplicate("new unique content")

        assert result is None

    @pytest.mark.asyncio
    async def test_finds_exact_duplicate(self):
        """Test finding exact duplicate within time window."""
        from datetime import datetime

        content = "Duplicate content"
        _ = content_hash(content)

        # Create a mock search result with matching content
        # Use current time to ensure it's within the window
        now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        mock_result = MagicMock()
        mock_result.content = content
        mock_result.uuid = "existing-uuid-123"
        mock_result.created_at = now_iso

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=[mock_result])

        with patch(
            "app.services.memory.service.get_memory_service",
            return_value=mock_service,
        ):
            result = await find_exact_duplicate(content, window_minutes=60)

        assert result == "existing-uuid-123"

    @pytest.mark.asyncio
    async def test_ignores_non_matching_content(self):
        """Test that non-matching content is ignored."""
        mock_result = MagicMock()
        mock_result.content = "Different content entirely"
        mock_result.uuid = "other-uuid"
        mock_result.created_at = "2026-01-24T00:00:00Z"

        mock_service = MagicMock()
        mock_service.search = AsyncMock(return_value=[mock_result])

        with patch(
            "app.services.memory.service.get_memory_service",
            return_value=mock_service,
        ):
            result = await find_exact_duplicate("My unique content")

        assert result is None

    @pytest.mark.asyncio
    async def test_handles_service_error(self):
        """Test graceful handling of service errors."""
        mock_service = MagicMock()
        mock_service.search = AsyncMock(side_effect=Exception("Connection failed"))

        with patch(
            "app.services.memory.service.get_memory_service",
            return_value=mock_service,
        ):
            result = await find_exact_duplicate("content")

        # Should return None on error, not raise
        assert result is None


class TestAddContentHashToEpisode:
    """Tests for add_content_hash_to_episode async function."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """Test that function returns True on success."""
        result = await add_content_hash_to_episode(
            episode_uuid="test-uuid",
            content="Test content",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        """Test that errors are handled gracefully."""
        # Since the current implementation just logs, this tests the error path
        # by providing invalid inputs that might cause issues
        result = await add_content_hash_to_episode(
            episode_uuid="",  # Empty UUID
            content="Content",
        )
        # Should still return True as current implementation just logs
        assert result is True
