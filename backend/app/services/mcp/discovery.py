"""MCP Tool Discovery Service.

Provides unified tool discovery and registration from MCP servers.
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.services.mcp.client import (
    MCPClientManager,
    get_mcp_client_manager,
)
from app.services.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredTool:
    """A tool discovered from any MCP source."""

    name: str
    description: str
    input_schema: dict[str, Any]
    source: str  # server name or "local"
    enabled: bool = True


class MCPToolDiscovery:
    """
    Service for discovering and registering tools from MCP servers.

    Provides a unified interface for:
    - Auto-discovering tools from configured MCP servers
    - Registering tools into the local ToolRegistry
    - Namespace management to avoid conflicts
    """

    def __init__(
        self,
        client_manager: MCPClientManager | None = None,
    ):
        """
        Initialize discovery service.

        Args:
            client_manager: MCP client manager (uses global if not provided)
        """
        self._client_manager = client_manager or get_mcp_client_manager()
        self._discovered_tools: dict[str, DiscoveredTool] = {}

    async def discover_all(self) -> list[DiscoveredTool]:
        """
        Discover tools from all connected MCP servers.

        Returns:
            List of discovered tools
        """
        self._discovered_tools.clear()

        for mcp_tool in self._client_manager.list_all_tools():
            tool = DiscoveredTool(
                name=f"{mcp_tool.server_name}:{mcp_tool.name}",
                description=mcp_tool.description,
                input_schema=mcp_tool.input_schema,
                source=mcp_tool.server_name,
            )
            self._discovered_tools[tool.name] = tool

        logger.info(f"Discovered {len(self._discovered_tools)} tools from MCP servers")
        return list(self._discovered_tools.values())

    def register_to_registry(self, registry: ToolRegistry) -> int:
        """
        Register discovered tools into a ToolRegistry.

        Args:
            registry: Target registry for tool registration

        Returns:
            Number of tools registered
        """
        count = 0
        for discovered in self._discovered_tools.values():
            if not discovered.enabled:
                continue

            tool = Tool(
                name=discovered.name,
                description=discovered.description,
                input_schema=discovered.input_schema,
            )
            registry.add(tool)
            count += 1

        logger.info(f"Registered {count} MCP tools to registry")
        return count

    def get_tool(self, name: str) -> DiscoveredTool | None:
        """Get a discovered tool by name."""
        return self._discovered_tools.get(name)

    def list_tools(self) -> list[DiscoveredTool]:
        """List all discovered tools."""
        return list(self._discovered_tools.values())

    def list_by_server(self, server_name: str) -> list[DiscoveredTool]:
        """List tools from a specific server."""
        return [t for t in self._discovered_tools.values() if t.source == server_name]

    def set_tool_enabled(self, name: str, enabled: bool) -> bool:
        """
        Enable or disable a specific tool.

        Args:
            name: Tool name to modify
            enabled: New enabled state

        Returns:
            True if tool was found and updated
        """
        tool = self._discovered_tools.get(name)
        if tool:
            tool.enabled = enabled
            return True
        return False


# Global discovery instance
_discovery: MCPToolDiscovery | None = None


def get_mcp_discovery() -> MCPToolDiscovery:
    """Get the global MCP tool discovery instance."""
    global _discovery
    if _discovery is None:
        _discovery = MCPToolDiscovery()
    return _discovery


def clear_mcp_discovery() -> None:
    """Clear the global discovery instance (for testing)."""
    global _discovery
    _discovery = None
