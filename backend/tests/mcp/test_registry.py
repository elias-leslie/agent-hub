"""Tests for MCP server registry."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.registry import (
    MCPRegistry,
    MCPServerInfo,
    clear_registry_cache,
    get_mcp_registry,
)


class TestMCPServerInfo:
    """Tests for MCPServerInfo dataclass."""

    def test_create_server_info(self):
        """Test creating server info."""
        info = MCPServerInfo(
            name="test-server",
            description="A test MCP server",
            url="http://localhost:8080",
            transport="sse",
        )

        assert info.name == "test-server"
        assert info.description == "A test MCP server"
        assert info.url == "http://localhost:8080"
        assert info.transport == "sse"
        assert info.is_local is False

    def test_to_dict(self):
        """Test converting to dictionary."""
        info = MCPServerInfo(
            name="test-server",
            description="Test",
            repository="https://github.com/test/server",
            packages=[{"name": "test-server", "version": "1.0.0"}],
        )

        result = info.to_dict()

        assert result["name"] == "test-server"
        assert result["repository"] == "https://github.com/test/server"
        assert len(result["packages"]) == 1


class TestMCPRegistry:
    """Tests for MCPRegistry."""

    def setup_method(self):
        """Reset registry before each test."""
        clear_registry_cache()

    def test_singleton_pattern(self):
        """Test registry is a singleton."""
        registry1 = get_mcp_registry()
        registry2 = get_mcp_registry()
        assert registry1 is registry2

    def test_cache_initially_invalid(self):
        """Test cache is initially invalid."""
        registry = MCPRegistry()
        assert registry._is_cache_valid() is False

    @pytest.mark.asyncio
    async def test_fetch_from_registry_success(self):
        """Test successful fetch from registry."""
        registry = MCPRegistry()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "servers": [
                {
                    "name": "filesystem-server",
                    "description": "File system MCP server",
                    "transport": "stdio",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__.return_value = mock_async_client
            mock_async_client.__aexit__.return_value = None
            mock_client.return_value = mock_async_client

            servers = await registry.fetch_from_registry()

            assert len(servers) == 1
            assert servers[0].name == "filesystem-server"

    @pytest.mark.asyncio
    async def test_fetch_from_registry_with_search(self):
        """Test fetch with search query."""
        registry = MCPRegistry()

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "name": "sql-server",
                "description": "SQL MCP server",
            }
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__.return_value = mock_async_client
            mock_async_client.__aexit__.return_value = None
            mock_client.return_value = mock_async_client

            servers = await registry.fetch_from_registry(search="sql")

            # Verify search param was passed
            call_args = mock_async_client.get.call_args
            assert call_args[1]["params"]["search"] == "sql"

    @pytest.mark.asyncio
    async def test_fetch_from_registry_error(self):
        """Test fetch handles errors gracefully."""
        import httpx

        registry = MCPRegistry()

        with patch("httpx.AsyncClient") as mock_client:
            mock_async_client = AsyncMock()
            mock_async_client.get = AsyncMock(side_effect=httpx.HTTPError("Connection error"))
            mock_async_client.__aenter__.return_value = mock_async_client
            mock_async_client.__aexit__.return_value = None
            mock_client.return_value = mock_async_client

            servers = await registry.fetch_from_registry()

            # Should return empty list on error, not raise
            assert servers == []

    @pytest.mark.asyncio
    async def test_parse_local_servers(self):
        """Test parsing local server config."""
        registry = MCPRegistry()

        with patch("app.services.mcp.registry.settings") as mock_settings:
            mock_settings.mcp_local_servers = (
                '[{"name": "local-server", "description": "Test", "url": "http://localhost:9000"}]'
            )
            mock_settings.mcp_registry_cache_ttl = 300

            servers = registry._parse_local_servers()

            assert len(servers) == 1
            assert servers[0].name == "local-server"
            assert servers[0].is_local is True

    @pytest.mark.asyncio
    async def test_parse_local_servers_empty(self):
        """Test parsing empty local server config."""
        registry = MCPRegistry()

        with patch("app.services.mcp.registry.settings") as mock_settings:
            mock_settings.mcp_local_servers = ""
            mock_settings.mcp_registry_cache_ttl = 300

            servers = registry._parse_local_servers()

            assert servers == []

    @pytest.mark.asyncio
    async def test_parse_local_servers_invalid_json(self):
        """Test parsing invalid JSON gracefully."""
        registry = MCPRegistry()

        with patch("app.services.mcp.registry.settings") as mock_settings:
            mock_settings.mcp_local_servers = "not valid json"
            mock_settings.mcp_registry_cache_ttl = 300

            servers = registry._parse_local_servers()

            # Should return empty list on error
            assert servers == []

    @pytest.mark.asyncio
    async def test_get_available_servers_combines_local_and_registry(self):
        """Test get_available_servers combines local and registry servers."""
        registry = MCPRegistry()

        with patch.object(registry, "_parse_local_servers") as mock_local:
            mock_local.return_value = [
                MCPServerInfo(name="local-1", description="Local", is_local=True)
            ]

            with patch.object(registry, "fetch_from_registry") as mock_fetch:
                mock_fetch.return_value = [MCPServerInfo(name="remote-1", description="Remote")]

                servers = await registry.get_available_servers()

                assert len(servers) == 2
                assert servers[0].name == "local-1"
                assert servers[0].is_local is True
                assert servers[1].name == "remote-1"
                assert servers[1].is_local is False

    @pytest.mark.asyncio
    async def test_get_available_servers_exclude_local(self):
        """Test excluding local servers."""
        registry = MCPRegistry()

        with patch.object(registry, "_parse_local_servers") as mock_local:
            mock_local.return_value = [
                MCPServerInfo(name="local-1", description="Local", is_local=True)
            ]

            with patch.object(registry, "fetch_from_registry") as mock_fetch:
                mock_fetch.return_value = [MCPServerInfo(name="remote-1", description="Remote")]

                servers = await registry.get_available_servers(include_local=False)

                # Should only have remote server
                assert len(servers) == 1
                assert servers[0].name == "remote-1"

    def test_clear_cache(self):
        """Test clearing cache."""
        registry = MCPRegistry()
        registry._cache = [MCPServerInfo(name="test", description="test")]
        from datetime import datetime

        registry._cache_time = datetime.utcnow()

        registry.clear_cache()

        assert registry._cache == []
        assert registry._cache_time is None

    @pytest.mark.asyncio
    async def test_search_servers(self):
        """Test search_servers convenience method."""
        registry = MCPRegistry()

        with patch.object(registry, "get_available_servers") as mock_get:
            mock_get.return_value = [MCPServerInfo(name="sql-server", description="SQL server")]

            servers = await registry.search_servers("sql")

            mock_get.assert_called_once_with(search="sql", include_local=True)
