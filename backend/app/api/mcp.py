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
            "prompts": False,  # Not implemented yet
            "logging": True,
            "tasks": True,  # Async operations supported
        },
        "tools_count": len(manager.list_tools()),
    }
