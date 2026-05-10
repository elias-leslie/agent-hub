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

    def test_accepts_topic_header_when_tier_is_provided(self):
        """Tier-aware validation should accept topic headers because tier lives in metadata."""
        EpisodeValidator.validate_content(
            '**Git Publish**: Use commit.sh --push --msg "description" for new commits. Use commit.sh --current --push for clean ahead branches.',
            tier="mandate",
        )

    def test_rejects_non_caveman_example_heavy_content(self) -> None:
        with pytest.raises(EpisodeValidationError) as exc:
            EpisodeValidator.validate_content(
                "**Prompt Hygiene**: Use strict prose. For example, explain every option.",
                tier="mandate",
            )

        assert "strict caveman gate" in str(exc.value).lower()
        assert "example markers found" in str(exc.value).lower()

    def test_bypass_compactness_skips_caveman_gate(self) -> None:
        # Long-sentence error normally fails the gate; bypass should let it through.
        long_content = (
            "**Topic**: Use the canonical runbook entry today before any other "
            "operator action because every fallback path eventually flows back."
        )
        EpisodeValidator.validate_content(
            long_content, tier="mandate", bypass_compactness=True
        )

    def test_bypass_compactness_still_enforces_other_rules(self) -> None:
        # Bypass should NOT skip header/atomic/verbose/delimiter rules.
        with pytest.raises(EpisodeValidationError):
            EpisodeValidator.validate_content(
                "no header here",
                tier="mandate",
                bypass_compactness=True,
            )

    def test_rejects_missing_bold_topic_header_when_tier_is_provided(self):
        """Tier-aware validation should still require a bold topic header."""
        with pytest.raises(EpisodeValidationError) as exc:
            EpisodeValidator.validate_content(
                'Use commit.sh --push --msg "description" for new commits. Use commit.sh --current --push for clean ahead branches.',
                tier="mandate",
            )

        assert "bold topic header" in str(exc.value).lower()

    @pytest.mark.parametrize(
        ("content", "needle"),
        [
            (
                "## Heartbeat: 20:56 EST\n\n### Orient\n- Active tasks: 1",
                "heartbeat journal",
            ),
            (
                "Subtask 53a75439 [refactor] required 3 attempts (1 self-fix, 1 guided).",
                "task execution log",
            ),
            (
                "**Pattern Walmart**: Document pattern for this household: 'receipt.pdf' classified as receipt.",
                "document-specific artifact",
            ),
        ],
    )
    def test_rejects_low_value_operational_or_app_state_content(
        self,
        content: str,
        needle: str,
    ) -> None:
        with pytest.raises(EpisodeValidationError) as exc:
            EpisodeValidator.validate_reusability(content)

        assert needle in str(exc.value).lower()


class TestEpisodeCreatorCreate:
    """Tests for EpisodeCreator.create()."""

    def setup_method(self):
        """Set up test fixtures."""
        # Mock the embedder and repository to avoid requiring real credentials
        self.mock_repo = AsyncMock()
        self.mock_embedder = AsyncMock()

        with patch(
            "app.services.memory.episode_creator.get_embedder",
            return_value=self.mock_embedder,
        ), patch(
            "app.services.memory.episode_creator.get_memory_repository",
            return_value=self.mock_repo,
        ):
            self.creator = EpisodeCreator()

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
    async def test_create_marks_format_valid_memory_source_compact(self):
        """Strict source-valid memories should not need immediate compaction review."""
        new_uuid = str(uuid.uuid4())
        mock_memory = MagicMock()
        mock_memory.id = uuid.UUID(new_uuid)
        self.mock_repo.create.return_value = mock_memory
        content = (
            "**Memory Authoring**: Use st memory format before st memory save. "
            "Why: source compactness prevents curation churn."
        )

        with patch(
            "app.services.memory.episode_creator_core.find_exact_duplicate",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await self.creator.create(
                content=content,
                name="memory_authoring",
                config=LEARNING,
                injection_tier="mandate",
            )

        assert result.success is True
        create_kwargs = self.mock_repo.create.await_args.kwargs
        metadata = create_kwargs["metadata"]
        assert metadata["compact_content"] == content
        assert metadata["compact_status"] == "source_ready"
        assert metadata["source_quality_method"] == "format_standard"
        assert metadata["source_compact_validated_at"]

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
    async def test_create_rejects_heartbeat_journal_for_learning_profile(self):
        """Learning profile should reject operational heartbeat journals."""
        result = await self.creator.create(
            content="## Heartbeat: 20:56 EST\n\n### Orient\n- Active tasks: 1",
            name="heartbeat_journal",
            config=LEARNING,
        )

        assert result.success is False
        assert result.validation_error is not None
        assert "heartbeat journal" in result.validation_error.lower()

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
        assert result.validation_error is not None
        assert "Memory creation error" in result.validation_error


class TestGetEpisodeCreator:
    """Tests for get_episode_creator factory function."""

    def setup_method(self):
        """Clear lru_cache before each test to avoid cross-test pollution."""
        get_episode_creator.cache_clear()

    def teardown_method(self):
        get_episode_creator.cache_clear()

    @patch("app.services.memory.episode_creator.get_embedder", return_value=AsyncMock())
    @patch("app.services.memory.episode_creator.get_memory_repository", return_value=AsyncMock())
    def test_default_scope(self, mock_repo, mock_embedder):
        """Test factory with default scope."""
        creator = get_episode_creator()
        assert creator.scope == MemoryScope.GLOBAL
        assert creator.scope_id is None

    @patch("app.services.memory.episode_creator.get_embedder", return_value=AsyncMock())
    @patch("app.services.memory.episode_creator.get_memory_repository", return_value=AsyncMock())
    def test_project_scope(self, mock_repo, mock_embedder):
        """Test factory with project scope."""
        creator = get_episode_creator(
            scope=MemoryScope.PROJECT,
            scope_id="my-project",
        )
        assert creator.scope == MemoryScope.PROJECT
        assert creator.scope_id == "my-project"

    @patch("app.services.memory.episode_creator.get_embedder", return_value=AsyncMock())
    @patch("app.services.memory.episode_creator.get_memory_repository", return_value=AsyncMock())
    def test_caching(self, mock_repo, mock_embedder):
        """Test that factory caches instances."""
        creator1 = get_episode_creator(scope=MemoryScope.GLOBAL)
        creator2 = get_episode_creator(scope=MemoryScope.GLOBAL)
        # Should be same cached instance
        assert creator1 is creator2
