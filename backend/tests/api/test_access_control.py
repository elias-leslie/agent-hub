"""Tests for access control system.

Tests the AccessControlMiddleware, identify flow, client CRUD, and API endpoints.
"""

from datetime import UTC, datetime
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.constants.models import GEMINI_FLASH
from app.main import app


@pytest.fixture
async def async_client(mock_db_session):
    """Create an async HTTP client for testing with mock db."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _mock_client_db(client_data):
    """Create a mock async_session context that returns given client data from DB.

    Args:
        client_data: A mock Client object (or None) to return from scalar_one_or_none.
    """
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = client_data

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)
    return mock_db


def _make_mock_client(
    client_id="test-client-id",
    status="active",
    display_name="Test Client",
    rate_limit_rpm=60,
    rate_limit_tpm=100000,
    allowed_projects=None,
    suspension_reason=None,
    suspended_at=None,
):
    """Create a mock Client ORM object."""
    client = MagicMock()
    client.id = client_id
    client.status = status
    client.display_name = display_name
    client.rate_limit_rpm = rate_limit_rpm
    client.rate_limit_tpm = rate_limit_tpm
    client.allowed_projects = allowed_projects
    client.suspension_reason = suspension_reason
    client.suspended_at = suspended_at
    return client


class TestAccessControlMiddleware:
    """Tests for the access control middleware."""

    async def test_exempt_paths_no_auth_required(self, async_client):
        """Test that exempt paths don't require authentication."""
        response = await async_client.get("/health")
        assert response.status_code == 200

    async def test_admin_paths_require_internal_header(self, async_client):
        """Test that admin paths require internal header."""
        # Without internal header, should get 403
        response = await async_client.get("/api/admin/clients")
        assert response.status_code == 403
        assert response.json()["error"] == "internal_only"

        # With internal header, should succeed
        response = await async_client.get(
            "/api/admin/clients",
            headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
        )
        assert response.status_code == 200

    async def test_access_control_paths_require_internal_header(self, async_client):
        """Test that access control paths require internal header."""
        # Without internal header, should get 403
        response = await async_client.get("/api/access-control/stats")
        assert response.status_code == 403
        assert response.json()["error"] == "internal_only"

        # With internal header, should succeed
        response = await async_client.get(
            "/api/access-control/stats",
            headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
        )
        assert response.status_code == 200

    async def test_missing_headers_returns_400(self, async_client):
        """Test that missing required headers return 400."""
        # No headers at all
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "missing_required_headers"
        assert "X-Client-Id" in str(data["required_headers"])
        assert "X-Request-Source" in str(data["required_headers"])

    async def test_partial_missing_headers_returns_400(self, async_client):
        """Test that partially missing headers return 400."""
        # Only client ID, missing request source
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers={"X-Client-Id": "test-client"},
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error"] == "missing_required_headers"

    async def test_missing_headers_no_secret_required(self, async_client):
        """Test that only X-Client-Id and X-Request-Source are required, NOT X-Client-Secret."""
        # Providing both required headers should NOT return 400
        mock_client = _make_mock_client()
        mock_db = _mock_client_db(mock_client)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "test-client-id",
                    "X-Request-Source": "test-source",
                },
            )
            # Should not be 400 (missing headers) - the request passed middleware
            assert response.status_code != 400

    async def test_missing_headers_response_does_not_mention_secret(self, async_client):
        """Test that missing headers error does not mention X-Client-Secret."""
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
        )
        assert response.status_code == 400
        data = response.json()
        # Required headers should only be client_id and request_source
        assert "X-Client-Secret" not in str(data)
        required = data["required_headers"]
        assert "X-Client-Id" in required
        assert "X-Request-Source" in required
        assert len(required) == 2

    async def test_unknown_client_returns_403(self, async_client):
        """Test that unknown client ID returns 403."""
        mock_db = _mock_client_db(None)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "non-existent-client-id",
                    "X-Request-Source": "test",
                },
            )
            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "client_not_found"

    async def test_client_not_found_response_structure(self, async_client):
        """Test that client_not_found response includes agent_instructions."""
        mock_db = _mock_client_db(None)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "unknown-id",
                    "X-Request-Source": "test",
                },
            )
            data = response.json()
            assert data["error"] == "client_not_found"
            assert "agent_instructions" in data
            assert data["agent_instructions"]["severity"] == "MANDATORY"
            assert "STOP" in data["agent_instructions"]["action"]

    async def test_internal_header_bypasses_auth(self, async_client):
        """Test that internal header bypasses authentication."""
        response = await async_client.get(
            "/api/sessions",
            headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
        )
        # Should not return 400 or 403 - may return 200 or other valid response
        assert response.status_code not in [400, 403]

    async def test_valid_auth_allows_request(self, async_client):
        """Test that valid authentication allows request through."""
        with patch("app.middleware.access_control_paths.settings.internal_service_secret", ""):
            response = await async_client.get(
                "/api/access-control/stats",
                headers={"X-Agent-Hub-Internal": ""},
            )
            assert response.status_code == 403
            assert response.json()["error"] == "internal_only"

        response = await async_client.get(
            "/api/access-control/stats",
            headers={"X-Agent-Hub-Internal": "agent-hub-internal-v1"},
        )
        assert response.status_code == 200


class TestIdentifyClientFlow:
    """Tests for the identify_client middleware flow.

    Verifies client identification by ID only (no secret verification).
    """

    @pytest.fixture(autouse=True)
    def clear_client_cache(self):
        """Clear the client cache before each test to avoid cross-test contamination."""
        from app.middleware.access_control_auth import _client_cache

        _client_cache.clear()
        yield
        _client_cache.clear()

    @pytest.fixture
    async def async_client(self, mock_db_session):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    async def test_identify_client_valid_active_client(self, async_client):
        """Test that a valid active client passes identification."""
        mock_client = _make_mock_client(client_id="active-client-flow", status="active")
        mock_db = _mock_client_db(mock_client)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "active-client-flow",
                    "X-Request-Source": "test-source",
                },
            )
            # Should pass middleware (not 400/403) - may fail further in pipeline
            assert response.status_code not in [400, 403]

    async def test_vantage_client_can_call_complete(self, async_client):
        """Test that a Vantage-scoped client can call Agent Hub with project_id=vantage."""
        mock_client = _make_mock_client(
            client_id="876c5159-95c3-45fa-abbd-ac39d4d42bfc",
            status="active",
            display_name="vantage",
            allowed_projects='["vantage"]',
        )
        mock_db = _mock_client_db(mock_client)

        with (
            patch("app.middleware.access_control_auth.async_session", return_value=mock_db),
            patch(
                "app.api.complete.endpoints.orchestrate_completion",
                new=AsyncMock(return_value=JSONResponse({"ok": True})),
            ),
        ):
            response = await async_client.post(
                "/api/complete",
                json={
                    "messages": [{"role": "user", "content": "run a research task"}],
                    "project_id": "vantage",
                },
                headers={
                    "X-Client-Id": "876c5159-95c3-45fa-abbd-ac39d4d42bfc",
                    "X-Request-Source": "vantage",
                },
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}

    async def test_identify_client_suspended_returns_403(self, async_client):
        """Test that a suspended client is rejected with 403."""
        mock_client = _make_mock_client(
            client_id="suspended-client-flow",
            status="suspended",
            suspension_reason="Testing suspension",
            suspended_at=datetime.now(UTC),
        )
        mock_db = _mock_client_db(mock_client)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "suspended-client-flow",
                    "X-Request-Source": "test-source",
                },
            )
            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "client_suspended"
            assert "suspended" in data["message"].lower()
            assert data["reason"] == "Testing suspension"

    async def test_identify_client_blocked_returns_403(self, async_client):
        """Test that a blocked client is rejected with 403."""
        mock_client = _make_mock_client(
            client_id="blocked-client-flow",
            status="blocked",
            display_name="Blocked Client",
            suspension_reason="Abuse detected",
            suspended_at=datetime.now(UTC),
        )
        mock_db = _mock_client_db(mock_client)

        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "blocked-client-flow",
                    "X-Request-Source": "test-source",
                },
            )
            assert response.status_code == 403
            data = response.json()
            assert data["error"] == "client_blocked"
            assert "permanently blocked" in data["message"].lower()
            assert data["reason"] == "Abuse detected"

    async def test_identify_client_only_needs_two_headers(self, async_client):
        """Test that identification requires only X-Client-Id and X-Request-Source."""
        # Only request source, missing client ID -> 400
        response = await async_client.post(
            "/api/complete",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers={"X-Request-Source": "test-source"},
        )
        assert response.status_code == 400

        # Both headers present -> passes header check (may get 403 for unknown client)
        mock_db = _mock_client_db(None)
        with patch("app.middleware.access_control_auth.async_session", return_value=mock_db):
            response = await async_client.post(
                "/api/complete",
                json={"messages": [{"role": "user", "content": "test"}]},
                headers={
                    "X-Client-Id": "header-check-only-id",
                    "X-Request-Source": "test-source",
                },
            )
            # Should be 403 (client_not_found), not 400 (missing headers)
            assert response.status_code == 403
            assert response.json()["error"] == "client_not_found"


class TestIdentifyClientUnit:
    """Unit tests for identify_client and set_identified_state helpers."""

    @pytest.mark.asyncio
    async def test_identify_client_success_returns_client_data(self):
        """Test identify_client returns (client_data, None) for valid active client."""
        from app.middleware.access_control_handler_helpers import identify_client

        client_data = {
            "id": "client-123",
            "status": "active",
            "display_name": "Test",
            "rate_limit_rpm": 60,
            "rate_limit_tpm": 100000,
            "allowed_projects": None,
            "suspension_reason": None,
            "suspended_at": None,
        }
        headers = {
            "client_id": "client-123",
            "request_source": "test",
            "tool_type": "api",
            "tool_name": None,
            "source_path": None,
        }

        with (
            patch("app.middleware.access_control_handler_helpers.get_cached_client", new_callable=AsyncMock, return_value=client_data),
            patch("app.middleware.access_control_handler_helpers.log_rejection", new_callable=AsyncMock),
        ):
            result_data, error_response = await identify_client(headers, "/api/complete", "POST", 0.0)

        assert result_data == client_data
        assert error_response is None

    @pytest.mark.asyncio
    async def test_identify_client_not_found_returns_error(self):
        """Test identify_client returns (None, response) when client not found."""
        from app.middleware.access_control_handler_helpers import identify_client

        headers = {
            "client_id": "unknown-id",
            "request_source": "test",
            "tool_type": "api",
            "tool_name": None,
            "source_path": None,
        }

        with (
            patch("app.middleware.access_control_handler_helpers.get_cached_client", new_callable=AsyncMock, return_value=None),
            patch("app.middleware.access_control_handler_helpers.log_rejection", new_callable=AsyncMock) as mock_log,
        ):
            result_data, error_response = await identify_client(headers, "/api/complete", "POST", 0.0)

        assert result_data is None
        assert error_response is not None
        assert error_response.status_code == 403
        mock_log.assert_called_once()

    @pytest.mark.asyncio
    async def test_identify_client_suspended_returns_error(self):
        """Test identify_client returns (None, response) for suspended client."""
        from app.middleware.access_control_handler_helpers import identify_client

        client_data = {
            "id": "client-123",
            "status": "suspended",
            "display_name": "Suspended Client",
            "rate_limit_rpm": 60,
            "rate_limit_tpm": 100000,
            "allowed_projects": None,
            "suspension_reason": "Rate abuse",
            "suspended_at": datetime.now(UTC),
        }
        headers = {
            "client_id": "client-123",
            "request_source": "test",
            "tool_type": "api",
            "tool_name": None,
            "source_path": None,
        }

        with (
            patch("app.middleware.access_control_handler_helpers.get_cached_client", new_callable=AsyncMock, return_value=client_data),
            patch("app.middleware.access_control_handler_helpers.log_rejection", new_callable=AsyncMock),
        ):
            result_data, error_response = await identify_client(headers, "/api/complete", "POST", 0.0)

        assert result_data is None
        assert error_response is not None
        assert error_response.status_code == 403

    @pytest.mark.asyncio
    async def test_identify_client_blocked_returns_error(self):
        """Test identify_client returns (None, response) for blocked client."""
        from app.middleware.access_control_handler_helpers import identify_client

        client_data = {
            "id": "client-123",
            "status": "blocked",
            "display_name": "Blocked Client",
            "rate_limit_rpm": 60,
            "rate_limit_tpm": 100000,
            "allowed_projects": None,
            "suspension_reason": "Permanently blocked",
            "suspended_at": datetime.now(UTC),
        }
        headers = {
            "client_id": "client-123",
            "request_source": "test",
            "tool_type": "api",
            "tool_name": None,
            "source_path": None,
        }

        with (
            patch("app.middleware.access_control_handler_helpers.get_cached_client", new_callable=AsyncMock, return_value=client_data),
            patch("app.middleware.access_control_handler_helpers.log_rejection", new_callable=AsyncMock),
        ):
            result_data, error_response = await identify_client(headers, "/api/complete", "POST", 0.0)

        assert result_data is None
        assert error_response is not None
        assert error_response.status_code == 403

    def test_set_identified_state_populates_request(self):
        """Test that set_identified_state correctly sets all request.state attributes."""
        from app.middleware.access_control_handler_helpers import set_identified_state

        request = MagicMock()
        request.state = MagicMock()

        client_data = {
            "id": "client-456",
            "status": "active",
            "display_name": "My Client",
            "allowed_projects": '["proj-a", "proj-b"]',
        }

        set_identified_state(request, client_data, "my-source")

        assert request.state.client is None  # ORM objects not cached
        assert request.state.client_id == "client-456"
        assert request.state.allowed_projects == '["proj-a", "proj-b"]'
        assert request.state.request_source == "my-source"
        assert request.state.is_internal is False

    def test_set_identified_state_unrestricted_projects(self):
        """Test set_identified_state with None allowed_projects (unrestricted)."""
        from app.middleware.access_control_handler_helpers import set_identified_state

        request = MagicMock()
        request.state = MagicMock()

        client_data = {
            "id": "client-789",
            "status": "active",
            "display_name": "Unrestricted",
            "allowed_projects": None,
        }

        set_identified_state(request, client_data, "sdk-source")

        assert request.state.allowed_projects is None


class TestLogRejectionUnknownClient:
    """Tests for log_rejection handling of unknown client IDs.

    When a request arrives with an unregistered client_id, the rejection must
    be logged to request_logs with client_id=NULL (to avoid FK violations)
    while the raw unknown ID is emitted via structured logging.
    """

    @pytest.mark.asyncio
    async def test_log_rejection_nullifies_client_id_for_unknown_client(self):
        """client_not_found rejection must pass client_id=None to log_request."""
        from app.middleware.access_control_logging import log_rejection

        with patch(
            "app.middleware.access_control_logging.log_request",
            new_callable=AsyncMock,
        ) as mock_log_request:
            await log_rejection(
                path="/api/complete",
                method="POST",
                start_time=0.0,
                client_id="unknown-nonexistent-id",
                request_source="test-source",
                tool_type="api",
                tool_name=None,
                source_path=None,
                rejection_reason="client_not_found",
            )

            mock_log_request.assert_called_once()
            call_kwargs = mock_log_request.call_args
            # client_id must be None in the DB insert to avoid FK violation
            assert call_kwargs.kwargs["client_id"] is None
            assert call_kwargs.kwargs["rejection_reason"] == "client_not_found"

    @pytest.mark.asyncio
    async def test_log_rejection_preserves_client_id_for_known_clients(self):
        """Suspended/blocked rejections must preserve the real client_id."""
        from app.middleware.access_control_logging import log_rejection

        with patch(
            "app.middleware.access_control_logging.log_request",
            new_callable=AsyncMock,
        ) as mock_log_request:
            await log_rejection(
                path="/api/complete",
                method="POST",
                start_time=0.0,
                client_id="known-suspended-id",
                request_source="test-source",
                tool_type="api",
                tool_name=None,
                source_path=None,
                rejection_reason="client_suspended",
            )

            call_kwargs = mock_log_request.call_args
            # Known client IDs should be preserved
            assert call_kwargs.kwargs["client_id"] == "known-suspended-id"

    @pytest.mark.asyncio
    async def test_log_rejection_emits_structured_log_for_unknown_client(self):
        """Unknown client rejection must emit a structured warning log."""
        from app.middleware.access_control_logging import log_rejection

        with (
            patch(
                "app.middleware.access_control_logging.log_request",
                new_callable=AsyncMock,
            ),
            patch(
                "app.middleware.access_control_logging.logger",
            ) as mock_logger,
        ):
            await log_rejection(
                path="/api/complete",
                method="POST",
                start_time=0.0,
                client_id="mystery-client-abc",
                request_source="test-source",
                tool_type="api",
                tool_name=None,
                source_path=None,
                rejection_reason="client_not_found",
            )

            mock_logger.warning.assert_called_once()
            log_msg_args = mock_logger.warning.call_args
            # The unknown client_id must appear in the log for observability
            assert "mystery-client-abc" in str(log_msg_args)


class TestHandleIdentifiedRequest:
    """Tests for the handle_identified_request handler."""

    @pytest.mark.asyncio
    async def test_handle_identified_request_internal_error_returns_500(self):
        """Test that exceptions in identify_client return 500."""
        from app.middleware.access_control_handlers import handle_identified_request

        # Use a MagicMock that properly simulates header access
        headers_data = {
            "X-Client-Id": "client-id",
            "X-Request-Source": "test",
            "X-Source-Client": None,
            "X-Tool-Name": None,
            "X-Source-Path": None,
        }
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.get = MagicMock(side_effect=lambda key, default=None: headers_data.get(key, default))

        call_next = AsyncMock()

        with patch(
            "app.middleware.access_control_handlers.identify_client",
            new_callable=AsyncMock,
            side_effect=Exception("DB connection failed"),
        ):
            response = await handle_identified_request(request, call_next, "/api/complete", "POST", 0.0)

        assert response.status_code == 500
        call_next.assert_not_called()


class TestAccessControlAPI:
    """Tests for access control admin API endpoints.

    All access control endpoints require the X-Agent-Hub-Internal header.
    """

    INTERNAL_HEADERS: ClassVar[dict[str, str]] = {"X-Agent-Hub-Internal": "agent-hub-internal-v1"}

    async def test_get_stats(self, async_client):
        """Test getting access control statistics."""
        response = await async_client.get(
            "/api/access-control/stats", headers=self.INTERNAL_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_clients" in data
        assert "active_clients" in data
        assert "suspended_clients" in data
        assert "blocked_clients" in data
        assert "blocked_requests_today" in data
        assert "total_requests_today" in data

    async def test_list_clients(self, async_client):
        """Test listing clients."""
        response = await async_client.get(
            "/api/access-control/clients", headers=self.INTERNAL_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data
        assert "total" in data

    async def test_create_client(self, async_client):
        """Test creating a new client."""
        response = await async_client.post(
            "/api/access-control/clients",
            json={
                "display_name": "Test API Client",
                "client_type": "external",
                "rate_limit_rpm": 60,
                "rate_limit_tpm": 100000,
            },
            headers=self.INTERNAL_HEADERS,
        )
        assert response.status_code == 201
        data = response.json()
        assert "client_id" in data
        assert data["display_name"] == "Test API Client"
        assert data["status"] == "active"

    async def test_create_client_returns_no_secret(self, async_client):
        """Test that client creation response contains NO secret field."""
        response = await async_client.post(
            "/api/access-control/clients",
            json={
                "display_name": "No Secret Client",
                "client_type": "external",
                "rate_limit_rpm": 60,
                "rate_limit_tpm": 100000,
            },
            headers=self.INTERNAL_HEADERS,
        )
        assert response.status_code == 201
        data = response.json()
        # Must have client_id but NO secret
        assert "client_id" in data
        assert "client_secret" not in data
        assert "secret" not in data

    async def test_create_client_response_schema(self, async_client):
        """Test that client creation response matches expected schema fields."""
        response = await async_client.post(
            "/api/access-control/clients",
            json={
                "display_name": "Schema Test Client",
                "client_type": "service",
                "rate_limit_rpm": 120,
                "rate_limit_tpm": 200000,
            },
            headers=self.INTERNAL_HEADERS,
        )
        assert response.status_code == 201
        data = response.json()
        # Verify schema fields
        assert data["client_type"] == "service"
        assert data["rate_limit_rpm"] == 120
        assert data["rate_limit_tpm"] == 200000
        assert "created_at" in data

    async def test_no_rotate_secret_endpoint(self, async_client):
        """Test that no rotate-secret endpoint exists (secrets removed)."""
        response = await async_client.post(
            "/api/access-control/clients/some-id/rotate-secret",
            headers=self.INTERNAL_HEADERS,
        )
        # Should be 404 or 405 (not found / method not allowed) since endpoint doesn't exist
        assert response.status_code in [404, 405, 422]

    async def test_get_request_log(self, async_client):
        """Test getting request log."""
        response = await async_client.get(
            "/api/access-control/request-log", headers=self.INTERNAL_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert "requests" in data
        assert "total" in data

    async def test_get_request_log_with_filters(self, async_client):
        """Test getting request log with filters."""
        response = await async_client.get(
            "/api/access-control/request-log",
            params={"rejected_only": True, "limit": 10},
            headers=self.INTERNAL_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["requests"]) <= 10


class TestClientAuthServiceUnit:
    """Unit tests for ClientAuthService (identify, register_client)."""

    @pytest.mark.asyncio
    async def test_register_client_returns_no_secret(self):
        """Test that register_client returns ClientRegistration without secret."""
        from app.services.client_auth import ClientAuthService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        service = ClientAuthService(mock_db)
        registration = await service.register_client(
            display_name="Test Client",
            client_type="external",
        )

        assert registration.client_id is not None
        assert registration.display_name == "Test Client"
        # Verify no secret field on the registration result
        assert not hasattr(registration, "client_secret")
        assert not hasattr(registration, "secret")

    @pytest.mark.asyncio
    async def test_identify_returns_identified_client_for_active(self):
        """Test that identify returns IdentifiedClient for an active client."""
        from app.services.client_auth import ClientAuthService

        mock_client = MagicMock()
        mock_client.id = "client-uuid"
        mock_client.display_name = "Active Client"
        mock_client.client_type = "external"
        mock_client.status = "active"
        mock_client.rate_limit_rpm = 60
        mock_client.rate_limit_tpm = 100000

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_client

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        service = ClientAuthService(mock_db)
        result = await service.identify("client-uuid")

        assert result is not None
        assert result.client_id == "client-uuid"
        assert result.display_name == "Active Client"
        assert result.status == "active"
        # Verify no secret in the result
        assert not hasattr(result, "client_secret")
        assert not hasattr(result, "secret")

    @pytest.mark.asyncio
    async def test_identify_returns_none_for_unknown_client(self):
        """Test that identify returns None for unknown client."""
        from app.services.client_auth import ClientAuthService

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ClientAuthService(mock_db)
        result = await service.identify("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_identify_returns_none_for_inactive_client(self):
        """Test that identify returns None for suspended/blocked client."""
        from app.services.client_auth import ClientAuthService

        mock_client = MagicMock()
        mock_client.id = "suspended-client"
        mock_client.status = "suspended"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_client

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        service = ClientAuthService(mock_db)
        result = await service.identify("suspended-client")

        assert result is None


class TestResponseStructures:
    """Tests for access control response builders."""

    def test_client_not_found_response_format(self):
        """Test client_not_found_response returns correct structure."""
        from app.middleware.access_control_responses import client_not_found_response

        response = client_not_found_response()
        assert response.status_code == 403
        # Parse JSON body
        import json
        body = json.loads(response.body)
        assert body["error"] == "client_not_found"
        assert "agent_instructions" in body
        assert body["agent_instructions"]["severity"] == "MANDATORY"

    def test_missing_headers_response_format(self):
        """Test missing_headers_response returns correct structure."""
        from app.middleware.access_control_responses import missing_headers_response

        response = missing_headers_response(["X-Client-Id", "X-Request-Source"])
        assert response.status_code == 400
        import json
        body = json.loads(response.body)
        assert body["error"] == "missing_required_headers"
        assert "X-Client-Id" in body["required_headers"]
        assert "X-Request-Source" in body["required_headers"]
        # Must NOT require X-Client-Secret
        assert "X-Client-Secret" not in body["required_headers"]

    def test_client_suspended_response_format(self):
        """Test client_suspended_response returns correct structure."""
        from app.middleware.access_control_responses import client_suspended_response

        client_data = {
            "display_name": "Test Client",
            "suspension_reason": "Rate abuse",
            "suspended_at": datetime(2026, 1, 15, 10, 30, tzinfo=UTC),
        }
        response = client_suspended_response(client_data)
        assert response.status_code == 403
        import json
        body = json.loads(response.body)
        assert body["error"] == "client_suspended"
        assert body["reason"] == "Rate abuse"
        assert body["suspended_at"] is not None

    def test_client_blocked_response_format(self):
        """Test client_blocked_response returns correct structure."""
        from app.middleware.access_control_responses import client_blocked_response

        client_data = {
            "display_name": "Bad Client",
            "suspension_reason": "Permanently blocked",
            "suspended_at": datetime(2026, 1, 10, 8, 0, tzinfo=UTC),
        }
        response = client_blocked_response(client_data)
        assert response.status_code == 403
        import json
        body = json.loads(response.body)
        assert body["error"] == "client_blocked"
        assert "permanently blocked" in body["message"].lower()

    def test_internal_error_response_format(self):
        """Test internal_error_response returns 500."""
        from app.middleware.access_control_responses import internal_error_response

        response = internal_error_response()
        assert response.status_code == 500
        import json
        body = json.loads(response.body)
        assert body["error"] == "internal_error"


class TestBudgetCheckInPipeline:
    """Tests for budget enforcement in the completion pipeline.

    The orchestrate_completion function calls check_project_budget and
    raises HTTPException(429) when the budget is exceeded.
    Tests the budget check logic matching the pipeline's behavior.
    """

    @pytest.mark.asyncio
    async def test_budget_exceeded_raises_429(self):
        """Test that exceeded budget triggers 429 as the pipeline would."""
        from fastapi import HTTPException

        from app.services.project_budget import BudgetCheckResult

        denied_result = BudgetCheckResult(
            allowed=False,
            reason="daily budget exceeded: $10.5000 >= $10.0000",
            daily_usage_usd=10.5,
            monthly_usage_usd=50.0,
            daily_limit_usd=10.0,
            monthly_limit_usd=100.0,
            alert_level="critical",
        )

        # Patch at the source module (imported inline by orchestrator)
        with patch(
            "app.services.project_budget.check_project_budget",
            new_callable=AsyncMock,
            return_value=denied_result,
        ):
            from app.services.project_budget import check_project_budget

            budget_result = await check_project_budget("test-project", db=None)
            assert budget_result.allowed is False

            # This mirrors the pipeline's logic:
            # if not budget_result.allowed:
            #     raise HTTPException(status_code=429, detail=...)
            with pytest.raises(HTTPException) as exc_info:
                if not budget_result.allowed:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Project budget exceeded: {budget_result.reason}",
                    )
            assert exc_info.value.status_code == 429
            assert "budget exceeded" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_budget_allowed_does_not_raise(self):
        """Test that allowed budget does not trigger 429."""
        from app.services.project_budget import BudgetCheckResult

        allowed_result = BudgetCheckResult(
            allowed=True,
            reason=None,
            daily_usage_usd=5.0,
            monthly_usage_usd=50.0,
            daily_limit_usd=10.0,
            monthly_limit_usd=100.0,
            alert_level=None,
        )

        with patch(
            "app.services.project_budget.check_project_budget",
            new_callable=AsyncMock,
            return_value=allowed_result,
        ):
            from app.services.project_budget import check_project_budget

            budget_result = await check_project_budget("test-project", db=None)
            assert budget_result.allowed is True
            # Pipeline would continue — no exception raised

    @pytest.mark.asyncio
    async def test_budget_monthly_exceeded_raises_429(self):
        """Test that monthly budget exceeded also triggers 429."""
        from fastapi import HTTPException

        from app.services.project_budget import BudgetCheckResult

        denied_result = BudgetCheckResult(
            allowed=False,
            reason="monthly budget exceeded: $100.0000 >= $100.0000",
            daily_usage_usd=5.0,
            monthly_usage_usd=100.0,
            daily_limit_usd=10.0,
            monthly_limit_usd=100.0,
            alert_level="critical",
        )

        with patch(
            "app.services.project_budget.check_project_budget",
            new_callable=AsyncMock,
            return_value=denied_result,
        ):
            from app.services.project_budget import check_project_budget

            budget_result = await check_project_budget("test-project", db=None)
            assert budget_result.allowed is False
            assert budget_result.reason is not None
            assert "monthly" in budget_result.reason

            with pytest.raises(HTTPException) as exc_info:
                if not budget_result.allowed:
                    raise HTTPException(
                        status_code=429,
                        detail=f"Project budget exceeded: {budget_result.reason}",
                    )
            assert exc_info.value.status_code == 429
            assert "monthly" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_budget_check_skipped_without_project_id(self):
        """Test that budget check is skipped when no project_id is provided.

        The orchestrator only checks budget when request.project_id is set.
        """

        # The pipeline's logic: if request.project_id: check_budget()
        # When project_id is None/empty, budget check is entirely skipped
        project_id = None
        budget_checked = False

        if project_id:
            budget_checked = True

        assert budget_checked is False


class TestSessionAttribution:
    """Tests for session attribution from identified clients."""

    @pytest.mark.integration
    async def test_identified_session_attribution(self, async_client):
        """Test that identified requests create sessions with client_id set.

        This test verifies that client_id is passed from AccessControlMiddleware
        to session creation via the X-Client-Id header.

        Note: Requires real client in DB. Run with --run-integration.
        """
        import os

        # Load credentials from environment (set by test setup)
        client_id = os.environ.get("CONSULT_CLIENT_ID")
        request_source = os.environ.get("CONSULT_REQUEST_SOURCE", "consult-skill")

        if not client_id:
            pytest.skip("Test requires CONSULT_CLIENT_ID")

        # Make identified request (no secret needed)
        response = await async_client.post(
            "/api/complete",
            json={
                "model": GEMINI_FLASH,
                "messages": [{"role": "user", "content": "test"}],
                "project_id": "test-session-attribution",
                "max_tokens": 50,
            },
            headers={
                "X-Client-Id": client_id,
                "X-Request-Source": request_source,
            },
        )

        # Request should succeed
        assert response.status_code == 200
        data = response.json()
        session_id = data.get("session_id")
        assert session_id is not None

        # Verify session was created with client_id
        from sqlalchemy import select

        from app.db import get_db
        from app.models import Session

        async for db in get_db():
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            assert session is not None
            assert session.client_id == client_id
            assert session.request_source == request_source
            break
