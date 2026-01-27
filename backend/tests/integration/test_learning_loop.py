"""Integration tests for memory learning loop.

Tests the complete flow of:
- Recording gotchas/patterns via API
- Retrieving relevant memories in subsequent queries
- Scope promotion during consolidation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.consolidation import (
    ConsolidationRequest,
    consolidate_task_memories,
)
from app.services.memory.service import (
    MemoryCategory,
    MemoryScope,
)
from app.services.memory.tools import (
    RecordGotchaRequest,
    RecordPatternRequest,
    record_gotcha,
    record_pattern,
)


class TestLearningLoop:
    """Integration tests for the complete learning loop."""

    @pytest.fixture
    def mock_graphiti(self):
        """Create mock graphiti client with test data."""
        graphiti = MagicMock()
        graphiti.add_episode = AsyncMock(return_value="episode-uuid-123")
        graphiti.search = AsyncMock(return_value=[])
        return graphiti

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_record_gotcha_stores_in_memory(self):
        """Test: Record gotcha via API, verify it's stored."""
        request = RecordGotchaRequest(
            gotcha="Async context managers must be awaited",
            context="When using aiohttp sessions",
            solution="Use 'async with' instead of 'with'",
            scope=MemoryScope.PROJECT,
        )

        with patch("app.services.memory.tools.get_memory_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.add_episode = AsyncMock(return_value="gotcha-uuid-456")
            mock_get_svc.return_value = mock_svc

            result = await record_gotcha(request)

            assert result.success is True
            assert result.episode_uuid == "gotcha-uuid-456"
            mock_svc.add_episode.assert_called_once()

            # Verify content includes gotcha, context, and solution
            call_args = mock_svc.add_episode.call_args
            content = call_args.kwargs["content"]
            assert "Gotcha: Async context managers" in content
            assert "Context: When using aiohttp" in content
            assert "Solution: Use 'async with'" in content

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_record_pattern_stores_with_correct_scope(self):
        """Test: Record pattern stores with correct scope metadata."""
        request = RecordPatternRequest(
            pattern="Use dependency injection for database sessions",
            applies_to="FastAPI route handlers",
            example="async def handler(db: AsyncSession = Depends(get_db))",
            scope=MemoryScope.GLOBAL,
        )

        with patch("app.services.memory.tools.get_memory_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.add_episode = AsyncMock(return_value="pattern-uuid-789")
            mock_get_svc.return_value = mock_svc

            result = await record_pattern(request)

            assert result.success is True
            assert result.episode_uuid == "pattern-uuid-789"

            # Verify get_memory_service was called with correct scope
            mock_get_svc.assert_called_once_with(scope=MemoryScope.GLOBAL, scope_id=None)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_patterns_and_gotchas_filters_by_type(self):
        """Test: get_patterns_and_gotchas returns type-filtered results."""
        # Create mock edges with different source descriptions
        mock_pattern_edge = MagicMock()
        mock_pattern_edge.uuid = "pattern-1"
        mock_pattern_edge.fact = "Use async/await for database calls"
        mock_pattern_edge.source_description = "coding standard pattern best practice"
        mock_pattern_edge.name = "coding pattern"
        mock_pattern_edge.score = 0.9
        mock_pattern_edge.created_at = "2026-01-17T12:00:00"
        mock_pattern_edge.source = "system"

        mock_gotcha_edge = MagicMock()
        mock_gotcha_edge.uuid = "gotcha-1"
        mock_gotcha_edge.fact = "Watch out for connection pool exhaustion"
        mock_gotcha_edge.source_description = "troubleshooting gotcha pitfall"
        mock_gotcha_edge.name = "troubleshooting guide"
        mock_gotcha_edge.score = 0.85
        mock_gotcha_edge.created_at = "2026-01-17T12:00:00"
        mock_gotcha_edge.source = "system"

        mock_irrelevant_edge = MagicMock()
        mock_irrelevant_edge.uuid = "other-1"
        mock_irrelevant_edge.fact = "Domain-specific fact"
        mock_irrelevant_edge.source_description = "domain knowledge"
        mock_irrelevant_edge.name = "domain fact"
        mock_irrelevant_edge.score = 0.7
        mock_irrelevant_edge.created_at = "2026-01-17T12:00:00"
        mock_irrelevant_edge.source = "chat"

        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(
            return_value=[mock_pattern_edge, mock_gotcha_edge, mock_irrelevant_edge]
        )

        with patch("app.services.memory.service.get_graphiti", return_value=mock_graphiti):
            from app.services.memory.service import MemoryService

            service = MemoryService(scope=MemoryScope.PROJECT)

            patterns, gotchas = await service.get_patterns_and_gotchas(
                query="database handling",
                num_results=10,
                min_score=0.5,
            )

            # Should only return pattern and gotcha, not domain knowledge
            assert len(patterns) == 1
            assert patterns[0].uuid == "pattern-1"
            assert "async/await" in patterns[0].content

            assert len(gotchas) == 1
            assert gotchas[0].uuid == "gotcha-1"
            assert "connection pool" in gotchas[0].content

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scope_promotion_on_consolidation(self):
        """Test: TASK-scoped memories promote to PROJECT on successful consolidation."""
        from app.services.memory.service import MemoryEpisode, MemoryListResult, MemorySource

        request = ConsolidationRequest(
            task_id="task-123",
            success=True,
            project_id="project-456",
            task_summary="Implemented async database pooling",
        )

        # Create mock episodes
        episodes = MemoryListResult(
            episodes=[
                MemoryEpisode(
                    uuid="mem-1",
                    name="Pattern",
                    content="Pattern: Use connection pooling",
                    source=MemorySource.SYSTEM,
                    category=MemoryCategory.REFERENCE,
                    source_description="coding standard",
                    created_at="2026-01-17T12:00:00",
                    valid_at="2026-01-17T12:00:00",
                    entities=[],
                    scope=MemoryScope.TASK,
                    scope_id="task-123",
                ),
                MemoryEpisode(
                    uuid="mem-2",
                    name="Gotcha",
                    content="Gotcha: Pool size must be < pg max_connections",
                    source=MemorySource.SYSTEM,
                    category=MemoryCategory.GUARDRAIL,
                    source_description="troubleshooting",
                    created_at="2026-01-17T12:00:00",
                    valid_at="2026-01-17T12:00:00",
                    entities=[],
                    scope=MemoryScope.TASK,
                    scope_id="task-123",
                ),
            ],
            total=2,
            cursor=None,
            has_more=False,
        )

        # Mock task service
        task_mock = MagicMock()
        task_mock.list_episodes = AsyncMock(return_value=episodes)
        task_mock.delete = AsyncMock()

        # Mock project service
        project_mock = MagicMock()
        project_mock.add_episode = AsyncMock(return_value="promoted-uuid")

        with patch("app.services.memory.consolidation.get_memory_service") as mock_get_svc:

            def get_service_side_effect(scope, scope_id=None):
                if scope == MemoryScope.TASK:
                    return task_mock
                elif scope == MemoryScope.PROJECT:
                    return project_mock
                return MagicMock()

            mock_get_svc.side_effect = get_service_side_effect

            result = await consolidate_task_memories(request)

            assert result.success is True
            assert result.promoted_count == 2  # Both episodes should be promoted
            # Verify project service was called for promotion
            mock_get_svc.assert_any_call(scope=MemoryScope.TASK, scope_id="task-123")

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_learning_loop_end_to_end(self):
        """Test: Complete learning loop - record, store, retrieve."""
        # Step 1: Record a gotcha
        gotcha_request = RecordGotchaRequest(
            gotcha="SQLAlchemy requires explicit commit for async sessions",
            context="When using async SQLAlchemy with FastAPI",
            solution="Call await session.commit() explicitly",
            scope=MemoryScope.PROJECT,
        )

        recorded_uuid = None

        with patch("app.services.memory.tools.get_memory_service") as mock_get_svc:
            mock_svc = MagicMock()
            mock_svc.add_episode = AsyncMock(return_value="learning-loop-uuid")
            mock_get_svc.return_value = mock_svc

            result = await record_gotcha(gotcha_request)
            assert result.success is True
            recorded_uuid = result.episode_uuid

        # Step 2: Verify the gotcha can be retrieved via patterns_and_gotchas
        mock_gotcha_edge = MagicMock()
        mock_gotcha_edge.uuid = recorded_uuid or "learning-loop-uuid"
        mock_gotcha_edge.fact = "SQLAlchemy requires explicit commit for async sessions"
        mock_gotcha_edge.source_description = "troubleshooting gotcha pitfall"
        mock_gotcha_edge.name = "async gotcha"
        mock_gotcha_edge.score = 0.95
        mock_gotcha_edge.created_at = "2026-01-17T12:00:00"
        mock_gotcha_edge.source = "system"

        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(return_value=[mock_gotcha_edge])

        with patch("app.services.memory.service.get_graphiti", return_value=mock_graphiti):
            from app.services.memory.service import MemoryService

            service = MemoryService(scope=MemoryScope.PROJECT)

            _patterns, gotchas = await service.get_patterns_and_gotchas(
                query="async SQLAlchemy database",
                num_results=10,
            )

            # Should find our recorded gotcha
            assert len(gotchas) == 1
            assert "explicit commit" in gotchas[0].content
