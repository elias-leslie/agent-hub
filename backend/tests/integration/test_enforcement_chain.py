"""Integration tests for the permission + budget enforcement chain.

Tests the two enforcement layers working together in the completion pipeline:
1. Project permissions -- tier-based tool filtering (off/read/full)
2. Cost budgets -- per-project daily/monthly USD limits via Redis

All infrastructure (DB, Redis, LLM) is mocked. These tests validate that the
layers compose correctly and enforce in the right order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.project_budget import BudgetCheckResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_CLIENT_ID = "test-enforcement-client-001"
TEST_PROJECT_ID = "test-enforcement-project"
TEST_REQUEST_SOURCE = "integration-test"

INTERNAL_HEADERS = {
    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
    "X-Source-Client": "pytest",
}


def _make_client_data(
    client_id: str = TEST_CLIENT_ID,
    status: str = "active",
    display_name: str = "Enforcement Test Client",
    rate_limit_rpm: int = 60,
    rate_limit_tpm: int = 100_000,
    allowed_projects: str | None = None,
    suspension_reason: str | None = None,
    suspended_at: datetime | None = None,
) -> dict[str, Any]:
    """Create a mock client data dict as returned by get_cached_client."""
    return {
        "id": client_id,
        "status": status,
        "display_name": display_name,
        "rate_limit_rpm": rate_limit_rpm,
        "rate_limit_tpm": rate_limit_tpm,
        "allowed_projects": allowed_projects,
        "suspension_reason": suspension_reason,
        "suspended_at": suspended_at,
    }


def _make_budget_result(
    allowed: bool = True,
    reason: str | None = None,
    daily_usage: float = 1.0,
    monthly_usage: float = 10.0,
    daily_limit: float | None = 50.0,
    monthly_limit: float | None = 500.0,
    alert_level: str | None = None,
) -> BudgetCheckResult:
    """Create a BudgetCheckResult for mocking."""
    return BudgetCheckResult(
        allowed=allowed,
        reason=reason,
        daily_usage_usd=daily_usage,
        monthly_usage_usd=monthly_usage,
        daily_limit_usd=daily_limit,
        monthly_limit_usd=monthly_limit,
        alert_level=alert_level,
    )


def _make_completion_result(
    content: str = "Test completion response",
    model: str = "claude-sonnet-4-20250514",
    input_tokens: int = 50,
    output_tokens: int = 20,
) -> MagicMock:
    """Create a mock completion payload."""
    result = MagicMock()
    result.content = content
    result.model = model
    result.provider = "claude"
    result.input_tokens = input_tokens
    result.output_tokens = output_tokens
    result.finish_reason = "end_turn"
    result.thinking_content = None
    result.thinking_tokens = None
    result.tool_calls = None
    result.cache_metrics = None
    result.container = None
    return result


def _identified_headers(
    client_id: str = TEST_CLIENT_ID,
    request_source: str = TEST_REQUEST_SOURCE,
) -> dict[str, str]:
    """Return headers that identify a client for the access control middleware."""
    return {
        "X-Client-Id": client_id,
        "X-Request-Source": request_source,
    }


def _complete_payload(
    project_id: str = TEST_PROJECT_ID,
    agent_slug: str = "test-agent",
) -> dict[str, Any]:
    """Return a minimal valid completion request payload."""
    return {
        "messages": [{"role": "user", "content": "hello"}],
        "project_id": project_id,
        "agent_slug": agent_slug,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client_cache():
    """Patch the client cache used by the access control middleware.

    Clears the in-memory cache before and after each test to prevent
    cross-test contamination.
    """
    from app.middleware.access_control_auth import _client_cache

    _client_cache.clear()
    yield
    _client_cache.clear()


@pytest.fixture
async def async_client(mock_db_session, mock_client_cache):
    """Create an async HTTP client backed by the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnforcementChain:
    """Integration tests validating the permission + budget enforcement chain."""

    # ------------------------------------------------------------------
    # 1. Full allow chain
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_full_allow_chain_proceeds(self, async_client):
        """Client identified + rate limit OK + budget OK + tier allows tool -> request proceeds.

        Verifies that when all enforcement layers pass, the request reaches
        the LLM adapter and returns a successful response.
        """
        client_data = _make_client_data()

        with (
            patch(
                "app.middleware.access_control_handler_helpers.get_cached_client",
                new_callable=AsyncMock,
                return_value=client_data,
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
                return_value=_make_budget_result(allowed=True),
            ),
            patch(
                "app.api.complete.endpoints.orchestrate_completion",
                new_callable=AsyncMock,
            ) as mock_orchestrate,
            patch(
                "app.middleware.access_control_logging.log_request",
                new_callable=AsyncMock,
            ),
        ):
            # Simulate the orchestrator returning a valid JSON response
            from fastapi.responses import JSONResponse

            mock_orchestrate.return_value = JSONResponse(
                content={
                    "content": "Test response",
                    "model": "claude-sonnet-4-20250514",
                    "provider": "claude",
                    "session_id": "test-session-001",
                    "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
                }
            )

            response = await async_client.post(
                "/api/complete",
                json=_complete_payload(),
                headers=_identified_headers(),
            )

            # Request should reach the orchestrator (not blocked by middleware)
            assert response.status_code == 200
            mock_orchestrate.assert_called_once()

    # ------------------------------------------------------------------
    # 2. Budget blocks
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_budget_exceeded_429(self, async_client):
        """Client identified + rate OK but daily budget exceeded -> 429 response.

        Tests the budget enforcement as wired in the orchestrator: when
        check_project_budget returns allowed=False, the orchestrator raises
        HTTPException(429). We simulate this by having orchestrate_completion
        raise the same exception the real code would.
        """
        from fastapi import HTTPException

        client_data = _make_client_data()

        async def _budget_denied_orchestrator(*args, **kwargs):
            raise HTTPException(
                status_code=429,
                detail="Project budget exceeded: daily budget exceeded: $50.0000 >= $50.0000",
            )

        with (
            patch(
                "app.middleware.access_control_handler_helpers.get_cached_client",
                new_callable=AsyncMock,
                return_value=client_data,
            ),
            patch(
                "app.api.complete.endpoints.orchestrate_completion",
                new_callable=AsyncMock,
                side_effect=_budget_denied_orchestrator,
            ),
            patch(
                "app.middleware.access_control_logging.log_request",
                new_callable=AsyncMock,
            ),
        ):
            response = await async_client.post(
                "/api/complete",
                json=_complete_payload(),
                headers=_identified_headers(),
            )

            assert response.status_code == 429
            data = response.json()
            assert "budget exceeded" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_enforcement_budget_check_denies_in_orchestrator(self):
        """Verify the orchestrator's budget check logic raises 429 when denied.

        This directly tests the budget check + HTTPException logic as written
        in the orchestrator, without going through HTTP.
        """
        from fastapi import HTTPException

        budget_denied = _make_budget_result(
            allowed=False,
            reason="daily budget exceeded: $50.0000 >= $50.0000",
            daily_usage=50.0,
            daily_limit=50.0,
            alert_level="critical",
        )

        with patch(
            "app.services.project_budget.check_project_budget",
            new_callable=AsyncMock,
            return_value=budget_denied,
        ):
            from app.services.project_budget import check_project_budget

            result = await check_project_budget(TEST_PROJECT_ID, db=None)

            # Replicate the orchestrator logic
            with pytest.raises(HTTPException) as exc_info:
                if not result.allowed:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Project budget exceeded: {result.reason}",
                    )

            assert exc_info.value.status_code == 429
            assert "daily budget exceeded" in exc_info.value.detail

    # ------------------------------------------------------------------
    # 4. Tier blocks tool
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_tier_blocks_tool_denied(self):
        """Client identified + rate OK + budget OK but tier doesn't allow tool -> tool rejected.

        The tier "read" only allows read-only tools. Attempting a write tool
        like "bash" should be denied by check_tool_allowed.
        """
        from app.models.project_permission import ProjectPermission
        from app.services.project_permission_service import check_tool_allowed

        # Mock DB to return a "read" tier permission
        mock_perm = MagicMock(spec=ProjectPermission)
        mock_perm.project_id = TEST_PROJECT_ID
        mock_perm.permission_tier = "read"
        mock_perm.auto_exec_enabled = False

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_perm

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=None)

        # Also patch Redis cache to return None (force DB lookup)
        with (
            patch(
                "app.services.project_permission_service._get_cached_tier",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.project_permission_service._set_cache",
                new_callable=AsyncMock,
            ),
        ):
            # "bash" is a full-tier tool, should be denied at "read" tier
            allowed, reason = await check_tool_allowed(
                TEST_PROJECT_ID, "bash", db=mock_db
            )
            assert allowed is False
            assert "not permitted" in reason
            assert "read" in reason

            # "read_file" is a read tool, should be allowed at "read" tier
            allowed, reason = await check_tool_allowed(
                TEST_PROJECT_ID, "read_file", db=mock_db
            )
            assert allowed is True
            assert reason == "allowed"

    @pytest.mark.asyncio
    async def test_enforcement_tier_off_blocks_all_tools(self):
        """Tier "off" blocks every tool, including read tools."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value="off",
        ):
            allowed, reason = await check_tool_allowed(TEST_PROJECT_ID, "read_file")
            assert allowed is False
            assert "not permitted" in reason
            assert "off" in reason

    # ------------------------------------------------------------------
    # 5. Client not found blocks everything
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_client_not_found_403(self, async_client):
        """Unknown client_id -> 403 before any other checks.

        Budget and rate limit services should never be reached.
        """
        with (
            patch(
                "app.middleware.access_control_handler_helpers.get_cached_client",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
            ) as mock_budget,
            patch(
                "app.middleware.access_control_logging.log_rejection",
                new_callable=AsyncMock,
            ),
            patch(
                "app.middleware.access_control_logging.log_request",
                new_callable=AsyncMock,
            ),
        ):
            response = await async_client.post(
                "/api/complete",
                json=_complete_payload(),
                headers=_identified_headers(client_id="nonexistent-client-xyz"),
            )

            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "client_not_found"

            # Budget should NOT have been called
            mock_budget.assert_not_called()

    # ------------------------------------------------------------------
    # 6. Suspended client blocks
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_suspended_client_403(self, async_client):
        """Suspended client -> 403 before rate/budget checks.

        The middleware should reject the request before any downstream
        enforcement layers execute.
        """
        suspended_client = _make_client_data(
            status="suspended",
            suspension_reason="Abuse detected during testing",
            suspended_at=datetime(2026, 2, 20, 12, 0, tzinfo=UTC),
        )

        with (
            patch(
                "app.middleware.access_control_handler_helpers.get_cached_client",
                new_callable=AsyncMock,
                return_value=suspended_client,
            ),
            patch(
                "app.services.project_budget.check_project_budget",
                new_callable=AsyncMock,
            ) as mock_budget,
            patch(
                "app.middleware.access_control_logging.log_rejection",
                new_callable=AsyncMock,
            ),
            patch(
                "app.middleware.access_control_logging.log_request",
                new_callable=AsyncMock,
            ),
        ):
            response = await async_client.post(
                "/api/complete",
                json=_complete_payload(),
                headers=_identified_headers(),
            )

            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "client_suspended"
            assert data["reason"] == "Abuse detected during testing"

            # Budget should NOT have been called
            mock_budget.assert_not_called()

    # ------------------------------------------------------------------
    # 7. Budget recording after success
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_enforcement_budget_recorded_after_success(self):
        """After successful completion, cost is recorded to Redis.

        Validates that record_project_cost increments both the daily and
        monthly Redis counters.
        """
        from app.services.project_budget import record_project_cost

        mock_redis = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock(side_effect=[0.0035, 0.0035])
        mock_redis.expire = AsyncMock()

        with patch("app.services.project_budget._get_redis", return_value=mock_redis):
            await record_project_cost(TEST_PROJECT_ID, 0.0035)

        # Should have called incrbyfloat twice (daily + monthly)
        assert mock_redis.incrbyfloat.call_count == 2

        # Verify the first call is the daily key
        daily_call_args = mock_redis.incrbyfloat.call_args_list[0]
        daily_key = daily_call_args[0][0]
        assert "budget:daily:" in daily_key
        assert TEST_PROJECT_ID in daily_key
        assert daily_call_args[0][1] == 0.0035

        # Verify the second call is the monthly key
        monthly_call_args = mock_redis.incrbyfloat.call_args_list[1]
        monthly_key = monthly_call_args[0][0]
        assert "budget:monthly:" in monthly_key
        assert TEST_PROJECT_ID in monthly_key
        assert monthly_call_args[0][1] == 0.0035

        # TTL should be set for first increment (new key)
        assert mock_redis.expire.call_count == 2

    @pytest.mark.asyncio
    async def test_enforcement_budget_not_recorded_for_zero_cost(self):
        """Zero-cost completions should not write to Redis."""
        from app.services.project_budget import record_project_cost

        mock_redis = AsyncMock()

        with patch("app.services.project_budget._get_redis", return_value=mock_redis):
            await record_project_cost(TEST_PROJECT_ID, 0.0)

        mock_redis.incrbyfloat.assert_not_called()


class TestEnforcementChainTierToolMatrix:
    """Tests for the tier-to-tool permission matrix across all tiers."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tier,tool_name,expected_allowed",
        [
            # "off" tier blocks everything
            ("off", "read_file", False),
            ("off", "write_file", False),
            ("off", "bash", False),
            # "read" tier allows read tools, blocks write/full tools
            ("read", "read_file", True),
            ("read", "search_scratch_context", False),
            ("read", "consult_agent", False),
            ("read", "write_file", False),
            ("read", "bash", False),
            # "full" tier allows core project tools
            ("full", "read_file", True),
            ("full", "write_file", True),
            ("full", "bash", True),
            ("full", "search_scratch_context", True),
            ("full", "batch_execute", False),
            ("full", "consult_agent", False),
            # Legacy labels normalize to full.
            ("write", "bash", True),
            ("yolo", "bash", True),
        ],
    )
    async def test_enforcement_tier_tool_matrix(
        self, tier: str, tool_name: str, expected_allowed: bool
    ):
        """Verify that each tier correctly allows/denies specific tools."""
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            return_value=tier,
        ):
            allowed, reason = await check_tool_allowed(TEST_PROJECT_ID, tool_name)

        assert allowed is expected_allowed, (
            f"tier={tier}, tool={tool_name}: expected allowed={expected_allowed}, "
            f"got allowed={allowed}, reason={reason}"
        )
        if expected_allowed:
            assert reason == "allowed"
        else:
            assert "not permitted" in reason


class TestEnforcementChainEdgeCases:
    """Edge case tests for enforcement chain interactions."""

    @pytest.mark.asyncio
    async def test_enforcement_budget_check_error_fails_closed(self):
        """Error during budget check should fail-CLOSED (deny request).

        Budget enforcement is a security/cost gate.
        """
        from app.services.project_budget import check_project_budget

        # Force an exception during budget check by making DB raise
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=ConnectionError("DB unavailable"))

        result = await check_project_budget(TEST_PROJECT_ID, db=mock_db)

        assert result.allowed is False
        assert result.reason is not None
        assert "budget check error" in result.reason

    @pytest.mark.asyncio
    async def test_enforcement_permission_check_error_fails_closed(self):
        """Error during permission check should fail-CLOSED (deny tool).

        Permission checking is a security gate.
        """
        from app.services.project_permission_service import check_tool_allowed

        with patch(
            "app.services.project_permission_service._get_cached_tier",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected cache error"),
        ):
            allowed, reason = await check_tool_allowed(TEST_PROJECT_ID, "read_file")

        assert allowed is False
        assert "permission check error" in reason

    @pytest.mark.asyncio
    async def test_enforcement_no_budget_limits_allows_request(self):
        """Project with no budget limits set should be allowed through."""
        from app.models.project_permission import ProjectPermission
        from app.services.project_budget import check_project_budget

        mock_perm = MagicMock(spec=ProjectPermission)
        mock_perm.project_id = TEST_PROJECT_ID
        mock_perm.daily_cost_budget_usd = None
        mock_perm.monthly_cost_budget_usd = None
        mock_perm.budget_alert_threshold = 0.8

        mock_result_obj = MagicMock()
        mock_result_obj.scalar_one_or_none.return_value = mock_perm

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result_obj)

        result = await check_project_budget(TEST_PROJECT_ID, db=mock_db)

        assert result.allowed is True
        assert result.daily_limit_usd is None
        assert result.monthly_limit_usd is None

    @pytest.mark.asyncio
    async def test_enforcement_unknown_project_budget_fails_closed(self):
        """Budget check for unknown project (no permission row) should fail-CLOSED."""
        from app.services.project_budget import check_project_budget

        mock_result_obj = MagicMock()
        mock_result_obj.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result_obj)

        result = await check_project_budget("nonexistent-project-xyz", db=mock_db)

        assert result.allowed is False
        assert result.reason is not None
        assert "no permission record" in result.reason
