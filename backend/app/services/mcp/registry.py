"""MCP Server Registry - Discover external MCP servers.

Fetches available MCP servers from the official registry
(registry.modelcontextprotocol.io) and optionally local configuration.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Official MCP Registry API
MCP_REGISTRY_BASE = settings.mcp_registry_url
MCP_REGISTRY_API = f"{MCP_REGISTRY_BASE}/v0"


@dataclass
class MCPServerInfo:
    """Information about an MCP server."""

    name: str
    description: str
    url: str | None = None
    transport: str = "stdio"
    repository: str | None = None
    packages: list[dict[str, str]] = field(default_factory=list)
    is_local: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "transport": self.transport,
            "repository": self.repository,
            "packages": self.packages,
            "is_local": self.is_local,
        }


class MCPRegistry:
    """Registry for discovering MCP servers."""

    def __init__(self) -> None:
        """Initialize registry with caching."""
        self._cache: list[MCPServerInfo] = []
        self._cache_time: datetime | None = None
        self._cache_ttl = timedelta(seconds=settings.mcp_registry_cache_ttl)

    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cache_time:
            return False
        return datetime.utcnow() - self._cache_time < self._cache_ttl

    def _parse_local_servers(self) -> list[MCPServerInfo]:
        """Parse locally configured MCP servers from settings."""
        if not settings.mcp_local_servers:
            return []

        try:
            local_config = json.loads(settings.mcp_local_servers)
            servers = []
            for server in local_config:
                servers.append(
                    MCPServerInfo(
                        name=server.get("name", "Unknown"),
                        description=server.get("description", ""),
                        url=server.get("url"),
                        transport=server.get("transport", "stdio"),
                        repository=server.get("repository"),
                        packages=server.get("packages", []),
                        is_local=True,
                    )
                )
            return servers
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse local MCP servers config: {e}")
            return []

    async def fetch_from_registry(
        self,
        search: str | None = None,
        limit: int = 50,
    ) -> list[MCPServerInfo]:
        """
        Fetch MCP servers from the official registry.

        Args:
            search: Optional search query to filter servers
            limit: Maximum number of servers to return (max 100)

        Returns:
            List of MCPServerInfo objects
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                params: dict[str, Any] = {"limit": min(limit, 100)}
                if search:
                    params["search"] = search

                response = await client.get(
                    f"{MCP_REGISTRY_API}/servers",
                    params=params,
                )
                response.raise_for_status()

                data = response.json()
                servers = []

                # Parse response - registry returns {"servers": [...]} or list
                server_list = data.get("servers", data) if isinstance(data, dict) else data

                for server in server_list:
                    servers.append(
                        MCPServerInfo(
                            name=server.get("name", "Unknown"),
                            description=server.get("description", ""),
                            url=server.get("url"),
                            transport=server.get("transport", "stdio"),
                            repository=server.get("repository"),
                            packages=server.get("packages", []),
                            is_local=False,
                        )
                    )

                return servers

        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch from MCP registry: {e}")
            return []
        except Exception as e:
            logger.error(f"Error fetching MCP servers: {e}")
            return []

    async def get_available_servers(
        self,
        search: str | None = None,
        include_local: bool = True,
        force_refresh: bool = False,
    ) -> list[MCPServerInfo]:
        """
        Get all available MCP servers (registry + local).

        Args:
            search: Optional search query
            include_local: Include locally configured servers
            force_refresh: Force refresh from registry (ignore cache)

        Returns:
            List of MCPServerInfo objects
        """
        servers: list[MCPServerInfo] = []

        # Add local servers first
        if include_local:
            servers.extend(self._parse_local_servers())

        # Check cache for registry servers (only if no search query)
        if not search and not force_refresh and self._is_cache_valid():
            servers.extend(self._cache)
        else:
            # Fetch from registry
            registry_servers = await self.fetch_from_registry(search=search)

            # Update cache if no search query
            if not search:
                self._cache = registry_servers
                self._cache_time = datetime.utcnow()

            servers.extend(registry_servers)

        return servers

    async def search_servers(self, query: str) -> list[MCPServerInfo]:
        """
        Search for MCP servers by name or functionality.

        Args:
            query: Search query (e.g., "filesystem", "sql", "github")

        Returns:
            List of matching MCPServerInfo objects
        """
        return await self.get_available_servers(search=query, include_local=True)

    def clear_cache(self) -> None:
        """Clear the server cache."""
        self._cache = []
        self._cache_time = None


# Singleton instance
_registry: MCPRegistry | None = None


def get_mcp_registry() -> MCPRegistry:
    """Get the singleton MCP registry instance."""
    global _registry
    if _registry is None:
        _registry = MCPRegistry()
    return _registry


def clear_registry_cache() -> None:
    """Clear the registry cache (for testing)."""
    if _registry:
        _registry.clear_cache()
