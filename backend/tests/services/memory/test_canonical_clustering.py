"""Tests for canonical clustering service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.canonical_clustering import (
    SIMILARITY_THRESHOLD,
    ClusteringResult,
    DisambiguationResult,
    SimilarityCheckResult,
    check_similarity,
    disambiguate_with_llm,
    handle_new_golden_standard,
    link_as_refinement,
    merge_into_golden,
)


class TestSimilarityCheckResult:
    """Tests for SimilarityCheckResult model."""

    def test_default_not_similar(self):
        """Test default values."""
        result = SimilarityCheckResult(is_similar=False)

        assert result.is_similar is False
        assert result.matched_uuid is None
        assert result.matched_content is None
        assert result.similarity_score == 0.0

    def test_similar_with_match(self):
        """Test similar result with match data."""
        result = SimilarityCheckResult(
            is_similar=True,
            matched_uuid="test-uuid-123",
            matched_content="Some content",
            similarity_score=0.92,
        )

        assert result.is_similar is True
        assert result.matched_uuid == "test-uuid-123"
        assert result.matched_content == "Some content"
        assert result.similarity_score == 0.92


class TestDisambiguationResult:
    """Tests for DisambiguationResult enum."""

    def test_rephrase_value(self):
        """Test REPHRASE enum value."""
        assert DisambiguationResult.REPHRASE.value == "rephrase"

    def test_variation_value(self):
        """Test VARIATION enum value."""
        assert DisambiguationResult.VARIATION.value == "variation"


class TestClusteringResult:
    """Tests for ClusteringResult model."""

    def test_created_action(self):
        """Test created action result."""
        result = ClusteringResult(
            action="created",
            episode_uuid="new-uuid",
            message="Created new golden standard",
        )

        assert result.action == "created"
        assert result.canonical_uuid is None

    def test_merged_action(self):
        """Test merged action result."""
        result = ClusteringResult(
            action="merged",
            episode_uuid="new-uuid",
            canonical_uuid="existing-uuid",
            message="Merged into existing",
        )

        assert result.action == "merged"
        assert result.canonical_uuid == "existing-uuid"


class TestSimilarityThreshold:
    """Tests for similarity threshold constant."""

    def test_threshold_value(self):
        """Test SIMILARITY_THRESHOLD is 0.85."""
        assert SIMILARITY_THRESHOLD == 0.85


class TestCheckSimilarity:
    """Tests for check_similarity function."""

    @pytest.mark.asyncio
    async def test_returns_not_similar_when_no_matches(self):
        """Test returns not similar when no golden standards match."""
        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(return_value=[])

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await check_similarity("New content", "global")

            assert result.is_similar is False
            assert result.matched_uuid is None

    @pytest.mark.asyncio
    async def test_returns_similar_when_above_threshold(self):
        """Test returns similar when score is above threshold."""
        mock_edge = MagicMock()
        mock_edge.score = 0.90  # Above 0.85 threshold
        mock_edge.uuid = "matched-uuid"
        mock_edge.fact = "Existing golden standard content"
        mock_edge.source_description = "golden_standard: rule"

        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(return_value=[mock_edge])

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await check_similarity("Similar content", "global")

            assert result.is_similar is True
            assert result.matched_uuid == "matched-uuid"
            assert result.similarity_score == 0.90

    @pytest.mark.asyncio
    async def test_ignores_non_golden_standard_matches(self):
        """Test ignores matches that are not golden standards."""
        mock_edge = MagicMock()
        mock_edge.score = 0.95
        mock_edge.uuid = "regular-uuid"
        mock_edge.fact = "Regular content"
        mock_edge.source_description = "regular: learning"  # Not golden_standard

        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(return_value=[mock_edge])

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await check_similarity("Content", "global")

            assert result.is_similar is False

    @pytest.mark.asyncio
    async def test_handles_search_error(self):
        """Test handles search errors gracefully."""
        mock_graphiti = MagicMock()
        mock_graphiti.search = AsyncMock(side_effect=Exception("Search failed"))

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await check_similarity("Content", "global")

            # Should return not similar on error (safe default)
            assert result.is_similar is False


class TestDisambiguateWithLLM:
    """Tests for disambiguate_with_llm function."""

    @pytest.mark.asyncio
    async def test_returns_rephrase_for_rephrase_response(self):
        """Test returns REPHRASE when LLM says rephrase."""
        mock_response = MagicMock()
        mock_response.content = "rephrase"

        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=mock_response)

        with patch(
            "app.services.memory.canonical_clustering.GeminiAdapter",
            return_value=mock_adapter,
        ):
            result = await disambiguate_with_llm("New content", "Existing content")

            assert result == DisambiguationResult.REPHRASE

    @pytest.mark.asyncio
    async def test_returns_variation_for_variation_response(self):
        """Test returns VARIATION when LLM says variation."""
        mock_response = MagicMock()
        mock_response.content = "variation"

        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=mock_response)

        with patch(
            "app.services.memory.canonical_clustering.GeminiAdapter",
            return_value=mock_adapter,
        ):
            result = await disambiguate_with_llm("New content", "Existing content")

            assert result == DisambiguationResult.VARIATION

    @pytest.mark.asyncio
    async def test_defaults_to_variation_on_unexpected_response(self):
        """Test defaults to VARIATION on unexpected LLM response."""
        mock_response = MagicMock()
        mock_response.content = "unknown_value"

        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(return_value=mock_response)

        with patch(
            "app.services.memory.canonical_clustering.GeminiAdapter",
            return_value=mock_adapter,
        ):
            result = await disambiguate_with_llm("New content", "Existing content")

            # Defaults to variation (safer - preserves info)
            assert result == DisambiguationResult.VARIATION

    @pytest.mark.asyncio
    async def test_defaults_to_variation_on_error(self):
        """Test defaults to VARIATION on LLM error."""
        mock_adapter = MagicMock()
        mock_adapter.complete = AsyncMock(side_effect=Exception("LLM error"))

        with patch(
            "app.services.memory.canonical_clustering.GeminiAdapter",
            return_value=mock_adapter,
        ):
            result = await disambiguate_with_llm("New content", "Existing content")

            # Defaults to variation on error (safer)
            assert result == DisambiguationResult.VARIATION


class TestMergeIntoGolden:
    """Tests for merge_into_golden function."""

    @pytest.mark.asyncio
    async def test_successful_merge(self):
        """Test successful merge updates synonyms."""
        mock_driver = MagicMock()
        mock_driver.execute_query = AsyncMock(
            return_value=([{"uuid": "golden-uuid", "synonym_count": 2}], None, None)
        )

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await merge_into_golden("golden-uuid", "New synonym content")

            assert result is True
            mock_driver.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_not_found(self):
        """Test merge returns False when golden not found."""
        mock_driver = MagicMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await merge_into_golden("nonexistent-uuid", "Content")

            assert result is False


class TestLinkAsRefinement:
    """Tests for link_as_refinement function."""

    @pytest.mark.asyncio
    async def test_successful_link(self):
        """Test successful REFINES relationship creation."""
        mock_driver = MagicMock()
        mock_driver.execute_query = AsyncMock(
            return_value=(
                [{"canonical": "golden-uuid", "variation": "new-uuid"}],
                None,
                None,
            )
        )

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await link_as_refinement("golden-uuid", "new-uuid")

            assert result is True

    @pytest.mark.asyncio
    async def test_link_nodes_not_found(self):
        """Test link returns False when nodes not found."""
        mock_driver = MagicMock()
        mock_driver.execute_query = AsyncMock(return_value=([], None, None))

        mock_graphiti = MagicMock()
        mock_graphiti.driver = mock_driver

        with patch(
            "app.services.memory.canonical_clustering.get_graphiti",
            return_value=mock_graphiti,
        ):
            result = await link_as_refinement("golden-uuid", "new-uuid")

            assert result is False


class TestHandleNewGoldenStandard:
    """Tests for handle_new_golden_standard function."""

    @pytest.mark.asyncio
    async def test_returns_create_when_no_similar(self):
        """Test returns 'create' when no similar content exists."""
        with patch(
            "app.services.memory.canonical_clustering.check_similarity",
            new_callable=AsyncMock,
            return_value=SimilarityCheckResult(is_similar=False),
        ):
            action, canonical_uuid = await handle_new_golden_standard(
                "Unique new content", "global"
            )

            assert action == "create"
            assert canonical_uuid is None

    @pytest.mark.asyncio
    async def test_returns_merge_for_rephrase(self):
        """Test returns 'merge' when LLM classifies as rephrase."""
        with (
            patch(
                "app.services.memory.canonical_clustering.check_similarity",
                new_callable=AsyncMock,
                return_value=SimilarityCheckResult(
                    is_similar=True,
                    matched_uuid="canonical-uuid",
                    matched_content="Existing content",
                    similarity_score=0.90,
                ),
            ),
            patch(
                "app.services.memory.canonical_clustering.disambiguate_with_llm",
                new_callable=AsyncMock,
                return_value=DisambiguationResult.REPHRASE,
            ),
            patch(
                "app.services.memory.canonical_clustering.merge_into_golden",
                new_callable=AsyncMock,
            ) as mock_merge,
        ):
            action, canonical_uuid = await handle_new_golden_standard(
                "Similar rephrased content", "global"
            )

            assert action == "merge"
            assert canonical_uuid == "canonical-uuid"
            mock_merge.assert_called_once_with("canonical-uuid", "Similar rephrased content")

    @pytest.mark.asyncio
    async def test_returns_link_for_variation(self):
        """Test returns 'link' when LLM classifies as variation."""
        with (
            patch(
                "app.services.memory.canonical_clustering.check_similarity",
                new_callable=AsyncMock,
                return_value=SimilarityCheckResult(
                    is_similar=True,
                    matched_uuid="canonical-uuid",
                    matched_content="Existing content",
                    similarity_score=0.90,
                ),
            ),
            patch(
                "app.services.memory.canonical_clustering.disambiguate_with_llm",
                new_callable=AsyncMock,
                return_value=DisambiguationResult.VARIATION,
            ),
        ):
            action, canonical_uuid = await handle_new_golden_standard(
                "Similar but different content", "global"
            )

            assert action == "link"
            assert canonical_uuid == "canonical-uuid"
