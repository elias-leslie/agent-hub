"""Tests for episode_creator module."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.episode_creator import (
    CreateResult,
    EpisodeCreator,
    get_episode_creator,
)
from app.services.memory.episode_validation import (
    EpisodeValidationError,
    EpisodeValidator,
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
    """Tests for EpisodeValidator.validate_content()."""

    def test_valid_declarative_content(self):
        """Test that declarative content passes validation."""
        content = "**Python Style**: Python files use 4-space indentation."
        # Should not raise exception
        EpisodeValidator.validate_content(content)

    def test_valid_factual_content(self):
        """Test that factual statements pass validation."""
        content = "**API Endpoint**: The API endpoint /api/users returns a JSON list."
        # Should not raise exception
        EpisodeValidator.validate_content(content)

    @pytest.mark.parametrize(
        "pattern",
        EpisodeValidator.VERBOSE_PATTERNS,
    )
    def test_rejects_verbose_patterns(self, pattern: str):
        """Test that verbose patterns are rejected."""
        content = f"**Topic**: This is content with {pattern} in it."
        with pytest.raises(EpisodeValidationError) as exc:
            EpisodeValidator.validate_content(content)

        assert "too verbose" in str(exc.value).lower()
        assert pattern in str(exc.value)

    def test_case_insensitive_pattern_detection(self):
        """Test that pattern detection is case insensitive."""
        content = "**Advice**: I RECOMMEND using this pattern."
        with pytest.raises(EpisodeValidationError) as exc:
            EpisodeValidator.validate_content(content)

        assert "i recommend" in str(exc.value)


class TestEpisodeCreatorCreate:
    """Tests for EpisodeCreator.create()."""

    def setup_method(self):
        """Set up test fixtures."""
        self.creator = EpisodeCreator()
        # Mock the new PostgreSQL-backed repository and embedder
        self.mock_repo = AsyncMock()
        self.mock_embedder = AsyncMock()
        self.creator._repo = self.mock_repo
        self.creator._embedder = self.mock_embedder

        # Default embedder returns a 768-dim vector
        self.mock_embedder.embed.return_value = [0.1] * 768

    @pytest.mark.asyncio
    async def test_create_success(self):
        """Test successful episode creation."""
        # Mock repo.create to return a new UUID
        new_uuid = str(uuid.uuid4())
        mock_memory = MagicMock()
        mock_memory.id = uuid.UUID(new_uuid)
        self.mock_repo.create.return_value = mock_memory

        with patch(
            "app.services.memory.episode_creator_core.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Python uses snake_case naming.",
                name="python_naming",
                config=LEARNING,
            )

        assert result.success is True
        assert result.uuid == new_uuid
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
        new_uuid = str(uuid.uuid4())
        mock_memory = MagicMock()
        mock_memory.id = uuid.UUID(new_uuid)
        self.mock_repo.create.return_value = mock_memory

        with patch(
            "app.services.memory.episode_creator_core.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Please let me know if you need help.",  # Would fail validation
                name="chat_message",
                config=CHAT_STREAM,  # validate=False
            )

        assert result.success is True
        assert result.uuid == new_uuid

    @pytest.mark.asyncio
    async def test_create_deduplication(self):
        """Test that duplicates are detected and skipped."""
        with patch(
            "app.services.memory.episode_creator_core.find_exact_duplicate",
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
        # Should not call repo.create when duplicate found
        self.mock_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_repo_error(self):
        """Test handling of repository errors."""
        self.mock_repo.create.side_effect = Exception("Connection failed")

        with patch(
            "app.services.memory.episode_creator_core.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content="Some content.",
                name="test",
                config=LEARNING,
            )

        assert result.success is False
        assert "Memory creation error" in result.validation_error


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
