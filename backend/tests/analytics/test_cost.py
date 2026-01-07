"""Tests for cost tracking service."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.cost_tracker import log_request_cost
from app.services.token_counter import estimate_cost, MODEL_PRICING


class TestLogRequestCost:
    """Tests for log_request_cost function."""

    @pytest.mark.asyncio
    async def test_log_request_creates_cost_log(self):
        """log_request_cost creates a CostLog entry."""
        # Mock database session
        mock_db = AsyncMock()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Log a request
        result = await log_request_cost(
            db=mock_db,
            session_id="test-session-123",
            model="claude-sonnet-4-5-20250514",
            input_tokens=1000,
            output_tokens=500,
        )

        # Verify CostLog was added
        assert len(added_objects) == 1
        cost_log = added_objects[0]
        assert cost_log.session_id == "test-session-123"
        assert cost_log.model == "claude-sonnet-4-5-20250514"
        assert cost_log.input_tokens == 1000
        assert cost_log.output_tokens == 500
        assert cost_log.cost_usd > 0

    @pytest.mark.asyncio
    async def test_log_request_calculates_correct_cost(self):
        """Cost is calculated correctly based on model pricing."""
        mock_db = AsyncMock()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Use known token counts for easy verification
        input_tokens = 1_000_000  # 1M tokens
        output_tokens = 500_000   # 500K tokens

        result = await log_request_cost(
            db=mock_db,
            session_id="test-session",
            model="claude-sonnet-4-5-20250514",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # Expected cost for claude-sonnet-4:
        # Input: 1M * $3/M = $3
        # Output: 500K * $15/M = $7.5
        # Total: $10.5
        cost_log = added_objects[0]
        expected_cost = 3.0 + 7.5  # $10.50
        assert abs(cost_log.cost_usd - expected_cost) < 0.01

    @pytest.mark.asyncio
    async def test_log_request_with_cached_tokens(self):
        """Cached tokens reduce calculated cost."""
        mock_db = AsyncMock()
        added_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        # Log request with cached tokens
        result = await log_request_cost(
            db=mock_db,
            session_id="test-session",
            model="claude-sonnet-4-5-20250514",
            input_tokens=1_000_000,
            output_tokens=0,
            cached_input_tokens=500_000,  # Half is cached
        )

        cost_log = added_objects[0]

        # Expected cost:
        # Uncached input: 500K * $3/M = $1.5
        # Cached input: 500K * $0.3/M = $0.15
        # Total: $1.65
        expected_cost = 1.5 + 0.15
        assert abs(cost_log.cost_usd - expected_cost) < 0.01

    @pytest.mark.asyncio
    async def test_log_request_different_models(self):
        """Different models have different pricing."""
        mock_db = AsyncMock()

        # Test Claude Sonnet
        sonnet_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: sonnet_objects.append(obj))
        await log_request_cost(
            db=mock_db,
            session_id="sonnet-session",
            model="claude-sonnet-4-5-20250514",
            input_tokens=1000,
            output_tokens=1000,
        )

        # Test Claude Haiku
        haiku_objects = []
        mock_db.add = MagicMock(side_effect=lambda obj: haiku_objects.append(obj))
        await log_request_cost(
            db=mock_db,
            session_id="haiku-session",
            model="claude-haiku-4-5-20250514",
            input_tokens=1000,
            output_tokens=1000,
        )

        sonnet_cost = sonnet_objects[0].cost_usd
        haiku_cost = haiku_objects[0].cost_usd

        # Haiku should be cheaper than Sonnet
        assert haiku_cost < sonnet_cost

    @pytest.mark.asyncio
    async def test_log_request_returns_cost_log(self):
        """log_request_cost returns the created CostLog."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        result = await log_request_cost(
            db=mock_db,
            session_id="test-session",
            model="claude-sonnet-4-5-20250514",
            input_tokens=100,
            output_tokens=50,
        )

        # Should return a CostLog object
        from app.models import CostLog
        assert isinstance(result, CostLog)
        assert result.session_id == "test-session"

    @pytest.mark.asyncio
    async def test_log_request_does_not_commit(self):
        """log_request_cost does not commit transaction."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()

        await log_request_cost(
            db=mock_db,
            session_id="test-session",
            model="claude-sonnet-4-5-20250514",
            input_tokens=100,
            output_tokens=50,
        )

        # Commit should NOT be called - caller manages transaction
        mock_db.commit.assert_not_called()


class TestEstimateCost:
    """Tests for estimate_cost function."""

    def test_estimate_cost_claude_sonnet(self):
        """Estimate cost for Claude Sonnet model."""
        cost = estimate_cost(
            input_tokens=10000,
            output_tokens=5000,
            model="claude-sonnet-4-5-20250514",
        )

        # Expected: 10K * $3/M + 5K * $15/M = $0.03 + $0.075 = $0.105
        assert abs(cost.total_cost_usd - 0.105) < 0.001
        assert cost.input_cost_usd > 0
        assert cost.output_cost_usd > 0

    def test_estimate_cost_claude_haiku(self):
        """Estimate cost for Claude Haiku model."""
        cost = estimate_cost(
            input_tokens=100000,
            output_tokens=50000,
            model="claude-haiku-4-5-20250514",
        )

        # Expected: 100K * $0.25/M + 50K * $1.25/M = $0.025 + $0.0625 = $0.0875
        assert abs(cost.total_cost_usd - 0.0875) < 0.001

    def test_estimate_cost_with_cached_tokens(self):
        """Cached tokens use discounted rate."""
        # All cached
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=0,
            model="claude-sonnet-4-5-20250514",
            cached_input_tokens=1_000_000,
        )

        # All tokens cached: 1M * $0.3/M = $0.30
        assert abs(cost.total_cost_usd - 0.30) < 0.001
        assert cost.cached_input_cost_usd > 0
        assert cost.input_cost_usd == 0  # No uncached input

    def test_estimate_cost_gemini(self):
        """Estimate cost for Gemini model."""
        cost = estimate_cost(
            input_tokens=1_000_000,
            output_tokens=500_000,
            model="gemini-2.0-flash",
        )

        # Expected: 1M * $0.075/M + 500K * $0.30/M = $0.075 + $0.15 = $0.225
        assert abs(cost.total_cost_usd - 0.225) < 0.001

    def test_estimate_cost_unknown_model_defaults_to_sonnet(self):
        """Unknown models default to Sonnet pricing."""
        cost = estimate_cost(
            input_tokens=1000,
            output_tokens=1000,
            model="unknown-model-xyz",
        )

        sonnet_cost = estimate_cost(
            input_tokens=1000,
            output_tokens=1000,
            model="claude-sonnet-4-5-20250514",
        )

        assert cost.total_cost_usd == sonnet_cost.total_cost_usd


import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


class TestCostAggregation:
    """Tests for /analytics/costs endpoint."""

    @pytest.fixture
    async def client(self):
        """Async test client."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

    @pytest.mark.asyncio
    async def test_aggregate_costs_returns_200(self, client: AsyncClient):
        """GET /api/analytics/costs returns 200."""
        response = await client.get("/api/analytics/costs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_aggregate_costs_response_structure(self, client: AsyncClient):
        """Response has expected structure."""
        response = await client.get("/api/analytics/costs")
        data = response.json()

        assert "aggregations" in data
        assert "total_cost_usd" in data
        assert "total_tokens" in data
        assert "total_requests" in data

        assert isinstance(data["aggregations"], list)
        assert isinstance(data["total_cost_usd"], (int, float))
        assert isinstance(data["total_tokens"], int)
        assert isinstance(data["total_requests"], int)

    @pytest.mark.asyncio
    async def test_aggregate_costs_group_by_model(self, client: AsyncClient):
        """Can group by model."""
        response = await client.get("/api/analytics/costs?group_by=model")
        assert response.status_code == 200
        data = response.json()
        assert "aggregations" in data

    @pytest.mark.asyncio
    async def test_aggregate_costs_group_by_project(self, client: AsyncClient):
        """Can group by project."""
        response = await client.get("/api/analytics/costs?group_by=project")
        assert response.status_code == 200
        data = response.json()
        assert "aggregations" in data

    @pytest.mark.asyncio
    async def test_aggregate_costs_group_by_day(self, client: AsyncClient):
        """Can group by day."""
        response = await client.get("/api/analytics/costs?group_by=day")
        assert response.status_code == 200
        data = response.json()
        assert "aggregations" in data

    @pytest.mark.asyncio
    async def test_aggregate_costs_with_model_filter(self, client: AsyncClient):
        """Can filter by model."""
        response = await client.get("/api/analytics/costs?model=claude")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_aggregate_costs_with_days_filter(self, client: AsyncClient):
        """Can filter by days."""
        response = await client.get("/api/analytics/costs?days=7")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_aggregate_costs_invalid_group_by(self, client: AsyncClient):
        """Invalid group_by returns 422."""
        response = await client.get("/api/analytics/costs?group_by=invalid")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_aggregate_costs_aggregation_fields(self, client: AsyncClient):
        """Aggregations have expected fields."""
        response = await client.get("/api/analytics/costs")
        data = response.json()

        # Even with no data, structure should be correct
        if data["aggregations"]:
            agg = data["aggregations"][0]
            assert "group_key" in agg
            assert "total_tokens" in agg
            assert "input_tokens" in agg
            assert "output_tokens" in agg
            assert "total_cost_usd" in agg
            assert "request_count" in agg
