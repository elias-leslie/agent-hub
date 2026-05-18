"""Tests for Agent Service.

Tests cover:
- Agent CRUD operations
- Redis caching
- Cache invalidation
- Version history
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.models import CLAUDE_OPUS, CLAUDE_SONNET, GEMINI_FLASH
from app.services.agent_service import AgentDTO, AgentService, get_agent_service


class TestAgentService:
    """Tests for AgentService class."""

    @pytest.fixture
    def service(self):
        """Create AgentService instance."""
        return AgentService()

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.delete = AsyncMock()
        return db

    @pytest.fixture
    def mock_agent(self):
        """Create a mock Agent model with all required fields."""
        agent = MagicMock()
        agent.id = 1
        agent.slug = "coder"
        agent.name = "Code Generator"
        agent.description = "Generates code"
        agent.system_prompt = "You are a coder."
        agent.primary_model_id = CLAUDE_SONNET
        agent.fallback_models = [GEMINI_FLASH]
        agent.escalation_model_id = CLAUDE_OPUS
        agent.strategies = {}
        agent.temperature = 0.7
        agent.max_tokens = None
        agent.is_active = True
        agent.is_coding_agent = True
        agent.memory_config = None
        agent.max_concurrency = None
        agent.max_subagent_concurrency = None
        agent.daily_token_budget = None
        agent.hourly_request_limit = None
        agent.version = 1
        agent.created_at = datetime.now(UTC)
        agent.updated_at = datetime.now(UTC)
        return agent

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD Operations
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_agent(self, service, mock_db, mock_agent):
        """Test get_by_slug returns agent when found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        # Bypass cache
        with (
            patch.object(service._cache, "get", return_value=None),
            patch.object(service._cache, "set"),
        ):
            result = await service.get_by_slug(mock_db, "coder")

        assert result is not None
        assert result.slug == "coder"
        assert result.name == "Code Generator"

    @pytest.mark.asyncio
    async def test_get_by_slug_returns_none_for_missing(self, service, mock_db):
        """Test get_by_slug returns None when agent not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch.object(service._cache, "get", return_value=None):
            result = await service.get_by_slug(mock_db, "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_slug_uses_cache(self, service, mock_db):
        """Test get_by_slug returns cached agent without DB query."""
        cached_dto = AgentDTO(
            id=1,
            slug="cached-agent",
            name="Cached",
            description=None,
            system_prompt="prompt",
            primary_model_id=CLAUDE_SONNET,
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=0.7,
            thinking_level=None,
            verbosity_level=None,
            is_active=True,
            is_coding_agent=False,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        with patch.object(service._cache, "get", return_value=cached_dto):
            result = await service.get_by_slug(mock_db, "cached-agent")

        assert result is not None
        assert result.slug == "cached-agent"
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_slug_overrides_cached_persona_name(self, service, mock_db):
        """Persona display name should resolve from the persona row, not cached agent config."""
        cached_dto = AgentDTO(
            id=1,
            slug="persona",
            name="Persona",
            description=None,
            system_prompt="prompt",
            primary_model_id=CLAUDE_SONNET,
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=0.7,
            thinking_level=None,
            verbosity_level=None,
            is_active=True,
            is_coding_agent=False,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        with (
            patch.object(service._cache, "get", return_value=cached_dto),
            patch(
                "app.services.agent_service.get_persona_display_name",
                new=AsyncMock(return_value="Avery"),
            ),
        ):
            result = await service.get_by_slug(mock_db, "persona")

        assert result is not None
        assert result.slug == "persona"
        assert result.name == "Avery"
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_by_id_returns_agent(self, service, mock_db, mock_agent):
        """Test get_by_id returns agent when found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        result = await service.get_by_id(mock_db, 1)

        assert result is not None
        assert result.id == 1

    @pytest.mark.asyncio
    async def test_list_agents_returns_active_only(self, service, mock_db, mock_agent):
        """Test list_agents with active_only=True."""
        mock_agent.slug = "persona"
        mock_agent.name = "Persona"
        mock_agent2 = MagicMock()
        mock_agent2.id = 2
        mock_agent2.slug = "reviewer"
        mock_agent2.name = "Reviewer"
        mock_agent2.description = None
        mock_agent2.system_prompt = "Review code"
        mock_agent2.primary_model_id = CLAUDE_SONNET
        mock_agent2.fallback_models = []
        mock_agent2.escalation_model_id = None
        mock_agent2.strategies = {}
        mock_agent2.temperature = 0.7
        mock_agent2.max_tokens = None
        mock_agent2.is_active = True
        mock_agent2.is_coding_agent = False
        mock_agent2.version = 1
        mock_agent2.created_at = datetime.now(UTC)
        mock_agent2.updated_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_agent, mock_agent2]
        mock_db.execute.return_value = mock_result

        with (
            patch(
                "app.services.agent_service._resolve_system_prompt",
                new=AsyncMock(side_effect=["You are persona.", "Review code"]),
            ),
            patch(
                "app.services.agent_service.get_persona_display_name",
                new=AsyncMock(return_value="Avery"),
            ),
        ):
            result = await service.list_agents(mock_db, active_only=True)

        assert len(result) == 2
        assert result[0].slug == "persona"
        assert result[0].name == "Avery"
        assert result[1].slug == "reviewer"
        assert result[1].name == "Reviewer"

    @pytest.mark.asyncio
    async def test_create_agent(self, service, mock_db, mock_agent):
        """Test creating a new agent."""

        # Mock the refresh to populate timestamps on the agent
        async def mock_refresh(agent):
            agent.id = 1
            agent.created_at = datetime.now(UTC)
            agent.updated_at = datetime.now(UTC)
            agent.version = 1
            agent.slug = "test-agent"
            agent.name = "Test Agent"
            agent.description = None
            agent.system_prompt = "You are a test agent."
            agent.primary_model_id = CLAUDE_SONNET
            agent.fallback_models = []
            agent.escalation_model_id = None
            agent.strategies = {}
            agent.temperature = 0.7
            agent.thinking_level = "high"
            agent.verbosity_level = "medium"
            agent.max_tokens = None
            agent.is_active = True
            agent.is_coding_agent = False
            agent.memory_config = None
            agent.max_concurrency = 4
            agent.max_subagent_concurrency = 2
            agent.daily_token_budget = 1000
            agent.hourly_request_limit = 25

        mock_db.refresh = mock_refresh

        with (
            patch.object(service._cache, "set"),
            patch("app.services.agent_service.sync_agent_system_prompt", new=AsyncMock()),
        ):
            agent = await service.create(
                mock_db,
                slug="test-agent",
                name="Test Agent",
                system_prompt="You are a test agent.",
                primary_model_id=CLAUDE_SONNET,
                thinking_level="high",
                verbosity_level="medium",
                max_concurrency=4,
                max_subagent_concurrency=2,
                daily_token_budget=1000,
                hourly_request_limit=25,
            )

        assert agent.slug == "test-agent"
        assert agent.name == "Test Agent"
        assert agent.thinking_level == "high"
        assert agent.verbosity_level == "medium"
        assert mock_db.add.call_count == 2

    @pytest.mark.asyncio
    async def test_update_agent(self, service, mock_db, mock_agent):
        """Test updating an existing agent."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        async def mock_refresh(agent):
            pass  # Timestamps already set on mock

        mock_db.refresh = mock_refresh

        with (
            patch.object(service._cache, "invalidate"),
            patch.object(service._cache, "set"),
        ):
            result = await service.update(
                mock_db,
                1,
                name="Updated Coder",
                thinking_level="minimal",
                verbosity_level="high",
                change_reason="Test update",
            )

        assert result is not None
        assert mock_agent.name == "Updated Coder"
        assert mock_agent.thinking_level == "minimal"
        assert mock_agent.verbosity_level == "high"
        assert mock_agent.version == 2

    @pytest.mark.asyncio
    async def test_update_can_clear_escalation_model(self, service, mock_db, mock_agent):
        """Explicit empty escalation assignment clears the stored model."""
        mock_agent.escalation_model_id = CLAUDE_OPUS
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        async def mock_refresh(agent):
            pass

        mock_db.refresh = mock_refresh

        with (
            patch.object(service._cache, "invalidate"),
            patch.object(service._cache, "set"),
        ):
            result = await service.update(
                mock_db,
                1,
                escalation_model_id="",
                change_reason="Clear escalation",
            )

        assert result is not None
        assert mock_agent.escalation_model_id is None

    @pytest.mark.asyncio
    async def test_update_returns_none_for_missing(self, service, mock_db):
        """Test update returns None when agent not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.update(mock_db, 999, name="Missing")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_soft(self, service, mock_db, mock_agent):
        """Test soft delete (deactivate) an agent."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with patch.object(service._cache, "invalidate"):
            result = await service.delete(mock_db, 1, hard_delete=False)

        assert result is True
        assert mock_agent.is_active is False

    @pytest.mark.asyncio
    async def test_delete_hard(self, service, mock_db, mock_agent):
        """Test hard delete an agent."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with patch.object(service._cache, "invalidate"):
            result = await service.delete(mock_db, 1, hard_delete=True)

        assert result is True
        mock_db.delete.assert_called_once_with(mock_agent)

    # ─────────────────────────────────────────────────────────────────────────
    # Cache Invalidation
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_update(self, service, mock_db, mock_agent):
        """Test that cache is invalidated when agent is updated."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        async def mock_refresh(agent):
            pass

        mock_db.refresh = mock_refresh

        with patch.object(service._cache, "invalidate") as mock_invalidate:
            with patch.object(service._cache, "set"):
                await service.update(mock_db, 1, name="Updated Coder")

            mock_invalidate.assert_called_once_with("coder")

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_delete(self, service, mock_db, mock_agent):
        """Test that cache is invalidated when agent is deleted."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_agent
        mock_db.execute.return_value = mock_result

        with patch.object(service._cache, "invalidate") as mock_invalidate:
            await service.delete(mock_db, 1, hard_delete=False)

            mock_invalidate.assert_called_once_with("coder")

    # ─────────────────────────────────────────────────────────────────────────
    # Version History
    # ─────────────────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_version_history(self, service, mock_db):
        """Test getting version history for an agent."""
        mock_version1 = MagicMock()
        mock_version1.version = 2
        mock_version1.config_snapshot = {"name": "Updated"}
        mock_version1.changed_by = "user"
        mock_version1.change_reason = "Updated name"
        mock_version1.created_at = datetime.now(UTC)

        mock_version2 = MagicMock()
        mock_version2.version = 1
        mock_version2.config_snapshot = {"name": "Original"}
        mock_version2.changed_by = "system"
        mock_version2.change_reason = "Initial creation"
        mock_version2.created_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_version1, mock_version2]
        mock_db.execute.return_value = mock_result

        history = await service.get_version_history(mock_db, 1)

        assert len(history) == 2
        assert history[0]["version"] == 2
        assert history[1]["version"] == 1


class TestAgentDTO:
    """Tests for AgentDTO dataclass."""

    def test_to_dict_and_from_dict(self):
        """Test round-trip serialization."""
        now = datetime.now(UTC)
        dto = AgentDTO(
            id=1,
            slug="test",
            name="Test",
            description="Desc",
            system_prompt="Prompt",
            primary_model_id=CLAUDE_SONNET,
            fallback_models=[GEMINI_FLASH],
            escalation_model_id=CLAUDE_OPUS,
            strategies={"retry": True},
            temperature=0.5,
            thinking_level=None,
            verbosity_level=None,
            is_active=True,
            is_coding_agent=True,
            memory_config=None,
            max_concurrency=None,
            max_subagent_concurrency=None,
            daily_token_budget=None,
            hourly_request_limit=None,
            version=1,
            created_at=now,
            updated_at=now,
        )

        data = dto.to_dict()
        restored = AgentDTO.from_dict(data)

        assert restored.slug == dto.slug
        assert restored.fallback_models == dto.fallback_models
        assert restored.strategies == dto.strategies
        assert restored.is_coding_agent == dto.is_coding_agent


class TestGetAgentService:
    """Tests for get_agent_service singleton."""

    def test_returns_singleton(self):
        """Test that get_agent_service returns singleton instance."""
        service1 = get_agent_service()
        service2 = get_agent_service()

        assert service1 is service2

    def test_returns_agent_service_instance(self):
        """Test that get_agent_service returns AgentService instance."""
        service = get_agent_service()

        assert isinstance(service, AgentService)
