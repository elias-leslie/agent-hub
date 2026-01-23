"""Tests for credential handling in SDK clients."""

import pytest
from unittest.mock import Mock, patch
from agent_hub import AgentHubClient, AsyncAgentHubClient


class TestSyncClientCredentials:
    """Test credential header injection in synchronous client."""

    def test_headers_injected_when_credentials_provided(self):
        """Verify headers are injected when credentials are provided."""
        client = AgentHubClient(
            base_url="http://test",
            client_id="test-id",
            client_secret="test-secret",
            request_source="test-source",
        )

        # Access the client to trigger initialization
        http_client = client._get_client()

        # Verify headers are set
        assert http_client.headers["X-Client-Id"] == "test-id"
        assert http_client.headers["X-Client-Secret"] == "test-secret"
        assert http_client.headers["X-Request-Source"] == "test-source"

        client.close()

    def test_no_auth_headers_without_credentials(self):
        """Verify backward compatibility - no auth headers when credentials not provided."""
        client = AgentHubClient(base_url="http://test")

        # Access the client to trigger initialization
        http_client = client._get_client()

        # Verify auth headers are not present
        assert "X-Client-Id" not in http_client.headers
        assert "X-Client-Secret" not in http_client.headers
        assert "X-Request-Source" not in http_client.headers

        client.close()

    def test_partial_credentials(self):
        """Verify partial credentials are handled correctly."""
        client = AgentHubClient(
            base_url="http://test",
            client_id="test-id",
            # client_secret omitted
            request_source="test-source",
        )

        http_client = client._get_client()

        # Only provided credentials should be in headers
        assert http_client.headers["X-Client-Id"] == "test-id"
        assert "X-Client-Secret" not in http_client.headers
        assert http_client.headers["X-Request-Source"] == "test-source"

        client.close()


class TestAsyncClientCredentials:
    """Test credential header injection in asynchronous client."""

    @pytest.mark.asyncio
    async def test_headers_injected_when_credentials_provided(self):
        """Verify headers are injected when credentials are provided."""
        client = AsyncAgentHubClient(
            base_url="http://test",
            client_id="test-id",
            client_secret="test-secret",
            request_source="test-source",
        )

        # Access the client to trigger initialization
        http_client = await client._get_client()

        # Verify headers are set
        assert http_client.headers["X-Client-Id"] == "test-id"
        assert http_client.headers["X-Client-Secret"] == "test-secret"
        assert http_client.headers["X-Request-Source"] == "test-source"

        await client.close()

    @pytest.mark.asyncio
    async def test_no_auth_headers_without_credentials(self):
        """Verify backward compatibility - no auth headers when credentials not provided."""
        client = AsyncAgentHubClient(base_url="http://test")

        # Access the client to trigger initialization
        http_client = await client._get_client()

        # Verify auth headers are not present
        assert "X-Client-Id" not in http_client.headers
        assert "X-Client-Secret" not in http_client.headers
        assert "X-Request-Source" not in http_client.headers

        await client.close()

    @pytest.mark.asyncio
    async def test_partial_credentials(self):
        """Verify partial credentials are handled correctly."""
        client = AsyncAgentHubClient(
            base_url="http://test",
            client_id="test-id",
            # client_secret omitted
            request_source="test-source",
        )

        http_client = await client._get_client()

        # Only provided credentials should be in headers
        assert http_client.headers["X-Client-Id"] == "test-id"
        assert "X-Client-Secret" not in http_client.headers
        assert http_client.headers["X-Request-Source"] == "test-source"

        await client.close()
