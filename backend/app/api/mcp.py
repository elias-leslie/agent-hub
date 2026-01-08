"""MCP API routes - Model Context Protocol endpoints.

Provides HTTP endpoints for MCP server management and tool access.
MCP clients connect via standard MCP transports (stdio, SSE).
"""

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.mcp import get_mcp_server

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])


class MCPHealthResponse(BaseModel):
    """MCP server health response."""

    status: str
    server_name: str
    tools_count: int
    tools: list[str]


class MCPToolListResponse(BaseModel):
    """List of available MCP tools."""

    tools: list[dict[str, Any]]
    count: int


@router.get("/health", response_model=MCPHealthResponse)
async def mcp_health() -> MCPHealthResponse:
    """
    Check MCP server health and status.

    Returns server name, tool count, and list of registered tools.
    """
    manager = get_mcp_server()
    health = await manager.health_check()
    return MCPHealthResponse(**health)


@router.get("/tools", response_model=MCPToolListResponse)
async def list_mcp_tools() -> MCPToolListResponse:
    """
    List all tools exposed by the MCP server.

    Returns tool names and their schemas.
    """
    manager = get_mcp_server()
    tool_names = manager.list_tools()

    # Get detailed tool info from the server
    tools: list[dict[str, Any]] = []
    server = manager.server

    if hasattr(server, "_tool_manager") and server._tool_manager:
        for name in tool_names:
            tool = server._tool_manager._tools.get(name)
            if tool:
                tools.append(
                    {
                        "name": name,
                        "description": tool.description if hasattr(tool, "description") else "",
                        "parameters": tool.parameters if hasattr(tool, "parameters") else {},
                    }
                )

    return MCPToolListResponse(tools=tools, count=len(tools))


@router.get("/info")
async def mcp_info() -> dict[str, Any]:
    """
    Get MCP server information.

    Returns server configuration and capabilities.
    """
    manager = get_mcp_server()
    server = manager.server

    return {
        "name": server.name,
        "version": "1.0.0",
        "protocol_version": "2025-11-25",
        "capabilities": {
            "tools": True,
            "resources": True,
            "prompts": True,
            "logging": True,
            "tasks": True,  # Async operations supported
        },
        "tools_count": len(manager.list_tools()),
    }


class MCPRegistryServerResponse(BaseModel):
    """External MCP server information."""

    name: str
    description: str
    url: str | None = None
    transport: str = "stdio"
    repository: str | None = None
    packages: list[dict[str, str]] = []
    is_local: bool = False


class MCPRegistryResponse(BaseModel):
    """Response for registry endpoint."""

    servers: list[MCPRegistryServerResponse]
    count: int
    cached: bool = False


@router.get("/registry", response_model=MCPRegistryResponse)
async def list_registry_servers(
    search: str | None = None,
    include_local: bool = True,
    force_refresh: bool = False,
) -> MCPRegistryResponse:
    """
    List available MCP servers from the registry.

    Fetches servers from the official MCP registry and optionally
    includes locally configured servers.

    Args:
        search: Optional search query to filter servers
        include_local: Include locally configured servers (default: True)
        force_refresh: Force refresh from registry (ignore cache)

    Returns:
        List of available MCP servers
    """
    from app.services.mcp.registry import get_mcp_registry

    registry = get_mcp_registry()
    servers = await registry.get_available_servers(
        search=search,
        include_local=include_local,
        force_refresh=force_refresh,
    )

    return MCPRegistryResponse(
        servers=[MCPRegistryServerResponse(**s.to_dict()) for s in servers],
        count=len(servers),
        cached=not force_refresh and registry._is_cache_valid(),
    )
