"""Tests for dedup module."""

from unittest.mock import AsyncMock, patch

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
        mock_repo = AsyncMock()
        mock_repo.find_duplicate.return_value = None

        with patch(
            "app.services.memory.dedup.get_memory_repository",
            return_value=mock_repo,
        ):
            result = await find_exact_duplicate("new unique content")

        assert result is None

    @pytest.mark.asyncio
    async def test_finds_exact_duplicate(self):
        """Test finding exact duplicate within time window."""
        content = "Duplicate content"

        mock_repo = AsyncMock()
        mock_repo.find_duplicate.return_value = "existing-uuid-123"

        with patch(
            "app.services.memory.dedup.get_memory_repository",
            return_value=mock_repo,
        ):
            result = await find_exact_duplicate(content, window_minutes=60)

        assert result == "existing-uuid-123"
        mock_repo.find_duplicate.assert_called_once_with(
            content, group_id=None, window_minutes=60,
        )

    @pytest.mark.asyncio
    async def test_passes_group_id(self):
        """Test that group_id is forwarded to repository."""
        mock_repo = AsyncMock()
        mock_repo.find_duplicate.return_value = None

        with patch(
            "app.services.memory.dedup.get_memory_repository",
            return_value=mock_repo,
        ):
            await find_exact_duplicate("content", group_id="my-group")

        mock_repo.find_duplicate.assert_called_once_with(
            "content", group_id="my-group", window_minutes=5,
        )

    @pytest.mark.asyncio
    async def test_handles_service_error(self):
        """Test graceful handling of service errors."""
        mock_repo = AsyncMock()
        mock_repo.find_duplicate.side_effect = Exception("Connection failed")

        with patch(
            "app.services.memory.dedup.get_memory_repository",
            return_value=mock_repo,
        ):
            result = await find_exact_duplicate("content")

        # Should return None on error, not raise
        assert result is None


class TestAddContentHashToEpisode:
    """Tests for add_content_hash_to_episode async function."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        """Test that function returns True on success."""
        mock_repo = AsyncMock()
        mock_repo.get_as_dict.return_value = {"metadata": {}}
        mock_repo.update = AsyncMock()

        with patch("app.services.memory.dedup.get_memory_repository", return_value=mock_repo):
            result = await add_content_hash_to_episode(
                episode_uuid="00000000-0000-0000-0000-000000000001",
                content="Test content",
            )
        assert result is True
        mock_repo.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        """Test that function returns False when memory not found."""
        mock_repo = AsyncMock()
        mock_repo.get_as_dict.return_value = None

        with patch("app.services.memory.dedup.get_memory_repository", return_value=mock_repo):
            result = await add_content_hash_to_episode(
                episode_uuid="00000000-0000-0000-0000-000000000002",
                content="Content",
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_error_gracefully(self):
        """Test that errors are handled gracefully."""
        mock_repo = AsyncMock()
        mock_repo.get_as_dict.side_effect = Exception("Database error")

        with patch("app.services.memory.dedup.get_memory_repository", return_value=mock_repo):
            result = await add_content_hash_to_episode(
                episode_uuid="00000000-0000-0000-0000-000000000003",
                content="Content",
            )
        assert result is False
