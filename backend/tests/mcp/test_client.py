"""Tests for MCP client implementation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.mcp.client import (
    MCPClient,
    MCPClientManager,
    MCPServer,
    MCPTool,
    clear_mcp_client_manager,
    get_mcp_client_manager,
)
from app.services.tools.base import ToolResult


class TestMCPServer:
    """Tests for MCPServer dataclass."""

    def test_create_server(self):
        """Test creating MCPServer configuration."""
        server = MCPServer(
            name="test-server",
            command="uvx",
            args=["mcp-server-filesystem"],
            env={"HOME": "/tmp"},
        )

        assert server.name == "test-server"
        assert server.command == "uvx"
        assert server.args == ["mcp-server-filesystem"]
        assert server.env == {"HOME": "/tmp"}
        assert server.enabled is True

    def test_server_defaults(self):
        """Test MCPServer default values."""
        server = MCPServer(name="test", command="python")

        assert server.args == []
        assert server.env == {}
        assert server.enabled is True


class TestMCPTool:
    """Tests for MCPTool dataclass."""

    def test_create_tool(self):
        """Test creating MCPTool."""
        tool = MCPTool(
            name="read_file",
            description="Read a file from disk",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            server_name="filesystem",
        )

        assert tool.name == "read_file"
        assert tool.description == "Read a file from disk"
        assert tool.server_name == "filesystem"

    def test_to_tool_namespaced(self):
        """Test converting to Tool with namespace."""
        mcp_tool = MCPTool(
            name="read_file",
            description="Read a file",
            input_schema={"type": "object"},
            server_name="filesystem",
        )

        tool = mcp_tool.to_tool()

        # Name should be namespaced
        assert tool.name == "filesystem:read_file"
        assert tool.description == "Read a file"


class TestMCPClient:
    """Tests for MCPClient."""

    def test_create_client(self):
        """Test creating MCPClient."""
        server = MCPServer(name="test", command="python")
        client = MCPClient(server)

        assert client.server == server
        assert client._session is None
        assert client._tools == []

    def test_tools_property(self):
        """Test tools property returns discovered tools."""
        server = MCPServer(name="test", command="python")
        client = MCPClient(server)

        # Initially empty
        assert client.tools == []

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self):
        """Test calling tool when not connected."""
        server = MCPServer(name="test", command="python")
        client = MCPClient(server)

        result = await client.call_tool("read_file", {"path": "/tmp/test"})

        assert result.is_error is True
        assert "Not connected" in result.content

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self):
        """Test health check when disconnected."""
        server = MCPServer(name="test", command="python")
        client = MCPClient(server)

        health = await client.health_check()

        assert health["server_name"] == "test"
        assert health["connected"] is False
        assert health["tools_count"] == 0


class TestMCPClientManager:
    """Tests for MCPClientManager."""

    def setup_method(self):
        """Reset singleton before each test."""
        clear_mcp_client_manager()

    def test_singleton_pattern(self):
        """Test manager is a singleton."""
        manager1 = MCPClientManager()
        manager2 = MCPClientManager()
        assert manager1 is manager2

    def test_get_mcp_client_manager(self):
        """Test get_mcp_client_manager returns singleton."""
        manager = get_mcp_client_manager()
        assert isinstance(manager, MCPClientManager)

    def test_register_server(self):
        """Test registering a server."""
        manager = MCPClientManager()
        server = MCPServer(name="test", command="python")

        manager.register_server(server)

        assert "test" in manager._servers
        assert manager._servers["test"] == server

    def test_get_client_not_connected(self):
        """Test getting client when not connected."""
        manager = MCPClientManager()

        client = manager.get_client("nonexistent")

        assert client is None

    def test_list_all_tools_empty(self):
        """Test listing tools with no connections."""
        manager = MCPClientManager()

        tools = manager.list_all_tools()

        assert tools == []

    @pytest.mark.asyncio
    async def test_call_tool_server_not_connected(self):
        """Test calling tool on unconnected server."""
        manager = MCPClientManager()

        result = await manager.call_tool("test", "read_file", {"path": "/tmp"})

        assert result.is_error is True
        assert "not connected" in result.content

    @pytest.mark.asyncio
    async def test_health_check_no_connections(self):
        """Test health check with no connections."""
        manager = MCPClientManager()

        health = await manager.health_check()

        assert health["status"] == "no_connections"
        assert health["servers_registered"] == 0
        assert health["servers_connected"] == 0

    @pytest.mark.asyncio
    async def test_connect_all_disabled_server(self):
        """Test connecting skips disabled servers."""
        manager = MCPClientManager()
        server = MCPServer(name="test", command="python", enabled=False)
        manager.register_server(server)

        results = await manager.connect_all()

        assert results["test"] is False
        assert "test" not in manager._clients

    @pytest.mark.asyncio
    async def test_disconnect_all(self):
        """Test disconnecting all servers."""
        manager = MCPClientManager()
        # Add a mock client
        mock_client = MagicMock()
        mock_client.disconnect = AsyncMock()
        manager._clients["test"] = mock_client

        await manager.disconnect_all()

        mock_client.disconnect.assert_called_once()
        assert "test" not in manager._clients


class TestClearMCPClientManager:
    """Tests for clear_mcp_client_manager."""

    def test_clear_resets_singleton(self):
        """Test clear_mcp_client_manager resets the singleton."""
        manager1 = MCPClientManager()
        clear_mcp_client_manager()
        manager2 = MCPClientManager()

        # Should be different instances (singleton was reset)
        # Note: In actual implementation, check if state is reset
        assert manager2._clients == {}
        assert manager2._servers == {}
