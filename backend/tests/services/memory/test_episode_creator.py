"""Tests for episode_creator module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.episode_creator import (
    VERBOSE_PATTERNS,
    CreateResult,
    EpisodeCreator,
    get_episode_creator,
)
from app.services.memory.ingestion_config import (
    CHAT_STREAM,
    GOLDEN_STANDARD,
    LEARNING,
)
from app.services.memory.service import MemoryScope


class TestCreateResult:
    """Tests for CreateResult dataclass."""

    def test_success_result(self):
        """Test successful creation result."""
        result = CreateResult(success=True, uuid="test-uuid-123")
        assert result.success is True
        assert result.uuid == "test-uuid-123"
        assert result.deduplicated is False
        assert result.validation_error is None

    def test_deduplicated_result(self):
        """Test deduplicated result."""
        result = CreateResult(success=True, uuid="existing-uuid", deduplicated=True)
        assert result.success is True
        assert result.uuid == "existing-uuid"
        assert result.deduplicated is True

    def test_validation_error_result(self):
        """Test validation error result."""
        result = CreateResult(success=False, validation_error="Too verbose")
        assert result.success is False
        assert result.uuid is None
        assert result.validation_error == "Too verbose"


class TestEpisodeCreatorValidation:
    """Tests for EpisodeCreator._validate_content()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.creator = EpisodeCreator()

    def test_valid_declarative_content(self):
        """Test that declarative content passes validation."""
        content = "Python files use 4-space indentation."
        error = self.creator._validate_content(content)
        assert error is None

    def test_valid_factual_content(self):
        """Test that factual statements pass validation."""
        content = "The API endpoint /api/users returns a JSON list."
        error = self.creator._validate_content(content)
        assert error is None

    @pytest.mark.parametrize(
        "pattern",
        VERBOSE_PATTERNS,
    )
    def test_rejects_verbose_patterns(self, pattern: str):
        """Test that verbose patterns are rejected."""
        content = f"This is content with {pattern} in it."
        error = self.creator._validate_content(content)
        assert error is not None
        assert "too verbose" in error.lower()
        assert pattern in error

    def test_case_insensitive_pattern_detection(self):
        """Test that pattern detection is case insensitive."""
        content = "I RECOMMEND using this pattern."
        error = self.creator._validate_content(content)
        assert error is not None
        assert "i recommend" in error


class TestEpisodeCreatorCreate:
    """Tests for EpisodeCreator.create()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.creator = EpisodeCreator()
        self.mock_graphiti = AsyncMock()
        self.creator._graphiti = self.mock_graphiti

    @pytest.mark.asyncio
    async def test_create_success(self):
        """Test successful episode creation."""
        # Mock successful Graphiti response
        mock_result = MagicMock()
        mock_result.episode.uuid = "new-uuid-456"
        mock_result.nodes = []
        mock_result.edges = []
        self.mock_graphiti.add_episode.return_value = mock_result

        with patch(
            "app.services.memory.episode_creator.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Python uses snake_case naming.",
                name="python_naming",
                config=LEARNING,
            )

        assert result.success is True
        assert result.uuid == "new-uuid-456"
        assert result.deduplicated is False

    @pytest.mark.asyncio
    async def test_create_validation_failure(self):
        """Test creation fails with verbose content when validation enabled."""
        result = await self.creator.create(
            content="You should always use this pattern.",
            name="bad_pattern",
            config=GOLDEN_STANDARD,  # validate=True
        )

        assert result.success is False
        assert result.validation_error is not None
        assert "too verbose" in result.validation_error.lower()

    @pytest.mark.asyncio
    async def test_create_skips_validation_for_chat_stream(self):
        """Test that CHAT_STREAM profile skips validation."""
        mock_result = MagicMock()
        mock_result.episode.uuid = "chat-uuid"
        mock_result.nodes = []
        mock_result.edges = []
        self.mock_graphiti.add_episode.return_value = mock_result

        with patch(
            "app.services.memory.episode_creator.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Please let me know if you need help.",  # Would fail validation
                name="chat_message",
                config=CHAT_STREAM,  # validate=False
            )

        assert result.success is True
        assert result.uuid == "chat-uuid"

    @pytest.mark.asyncio
    async def test_create_deduplication(self):
        """Test that duplicates are detected and skipped."""
        with patch(
            "app.services.memory.episode_creator.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value="existing-uuid-789",
        ):
            result = await self.creator.create(
                content="Duplicate content.",
                name="duplicate",
                config=LEARNING,  # deduplicate=True
            )

        assert result.success is True
        assert result.uuid == "existing-uuid-789"
        assert result.deduplicated is True
        # Should not call Graphiti when duplicate found
        self.mock_graphiti.add_episode.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_graphiti_error(self):
        """Test handling of Graphiti errors."""
        self.mock_graphiti.add_episode.side_effect = Exception("Connection failed")

        with patch(
            "app.services.memory.episode_creator.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Some content.",
                name="test",
                config=LEARNING,
            )

        assert result.success is False
        assert "Graphiti error" in result.validation_error


class TestEpisodeCreatorSourceDescription:
    """Tests for EpisodeCreator._build_source_description()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.creator = EpisodeCreator()

    def test_golden_standard_description(self):
        """Test source description for golden standards."""
        description = self.creator._build_source_description(GOLDEN_STANDARD)
        assert "mandate" in description
        assert "tier:always" in description
        assert "source:golden_standard" in description
        assert "confidence:100" in description

    def test_learning_description(self):
        """Test source description for learning profile."""
        description = self.creator._build_source_description(LEARNING)
        assert "pattern" in description
        assert "tier:medium" in description
        assert "golden_standard" not in description

    def test_chat_stream_description(self):
        """Test source description for chat stream profile."""
        description = self.creator._build_source_description(CHAT_STREAM)
        assert "session" in description
        assert "tier:low" in description


class TestGetEpisodeCreator:
    """Tests for get_episode_creator factory function."""

    def test_default_scope(self):
        """Test factory with default scope."""
        creator = get_episode_creator()
        assert creator.scope == MemoryScope.GLOBAL
        assert creator.scope_id is None

    def test_project_scope(self):
        """Test factory with project scope."""
        creator = get_episode_creator(
            scope=MemoryScope.PROJECT,
            scope_id="my-project",
        )
        assert creator.scope == MemoryScope.PROJECT
        assert creator.scope_id == "my-project"

    def test_caching(self):
        """Test that factory caches instances."""
        creator1 = get_episode_creator(scope=MemoryScope.GLOBAL)
        creator2 = get_episode_creator(scope=MemoryScope.GLOBAL)
        # Should be same cached instance
        assert creator1 is creator2


class TestEpisodeCreatorContentHash:
    """Tests for EpisodeCreator._get_content_hash()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.creator = EpisodeCreator()

    def test_content_hash_consistency(self):
        """Test that same content produces same hash."""
        content = "Test content for hashing."
        hash1 = self.creator._get_content_hash(content)
        hash2 = self.creator._get_content_hash(content)
        assert hash1 == hash2

    def test_content_hash_different_content(self):
        """Test that different content produces different hashes."""
        hash1 = self.creator._get_content_hash("Content A")
        hash2 = self.creator._get_content_hash("Content B")
        assert hash1 != hash2
