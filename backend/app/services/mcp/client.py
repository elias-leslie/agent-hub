"""MCP Client - Connect to external MCP servers.

Enables Agent Hub to consume tools from external MCP servers,
providing access to file systems, databases, web services, etc.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.services.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class MCPServer:
    """Configuration for an external MCP server."""

    name: str
    command: str  # Command to start the server (stdio transport)
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    # OAuth authentication for HTTP/SSE transports
    bearer_token: str | None = None  # Bearer token for authenticated servers
    oauth_token_url: str | None = None  # URL to refresh OAuth token


@dataclass
class MCPTool:
    """Tool discovered from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str  # Which server provides this tool

    def to_tool(self) -> Tool:
        """Convert to base Tool type."""
        return Tool(
            name=f"{self.server_name}:{self.name}",  # Namespace by server
            description=self.description,
            input_schema=self.input_schema,
        )


class MCPClient:
    """Client for connecting to a single MCP server."""

    def __init__(self, server: MCPServer):
        """
        Initialize MCP client for a server.

        Args:
            server: Server configuration
        """
        self.server = server
        self._session: ClientSession | None = None
        self._tools: list[MCPTool] = []

    async def connect(self) -> bool:
        """
        Connect to the MCP server and discover tools.

        Returns:
            True if connected successfully
        """
        try:
            server_params = StdioServerParameters(
                command=self.server.command,
                args=self.server.args,
                env=self.server.env if self.server.env else None,
            )

            # Create client connection
            self._read, self._write = await stdio_client(server_params).__aenter__()
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()

            # Initialize and discover tools
            await self._session.initialize()
            await self._discover_tools()

            logger.info(
                f"Connected to MCP server '{self.server.name}': {len(self._tools)} tools available"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to connect to MCP server '{self.server.name}': {e}")
            return False

    async def _discover_tools(self) -> None:
        """Discover available tools from the server."""
        if not self._session:
            return

        try:
            tools_response = await self._session.list_tools()
            self._tools = []

            for tool in tools_response.tools:
                mcp_tool = MCPTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                    server_name=self.server.name,
                )
                self._tools.append(mcp_tool)

        except Exception as e:
            logger.error(f"Failed to discover tools from '{self.server.name}': {e}")

    @property
    def tools(self) -> list[MCPTool]:
        """Get discovered tools."""
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool (without server prefix)
            arguments: Tool input arguments

        Returns:
            ToolResult with output or error
        """
        if not self._session:
            return ToolResult(
                tool_use_id="",
                content=f"Not connected to server '{self.server.name}'",
                is_error=True,
            )

        try:
            result = await self._session.call_tool(tool_name, arguments)

            # Extract text content from result
            content_parts: list[str] = []
            for content in result.content:
                if hasattr(content, "text"):
                    content_parts.append(content.text)
                elif hasattr(content, "data"):
                    content_parts.append(f"[Binary data: {len(content.data)} bytes]")

            return ToolResult(
                tool_use_id="",
                content="\n".join(content_parts) if content_parts else "No output",
                is_error=result.isError if hasattr(result, "isError") else False,
            )

        except Exception as e:
            logger.error(f"Tool call failed on '{self.server.name}': {e}")
            return ToolResult(
                tool_use_id="",
                content=f"Error calling tool: {e}",
                is_error=True,
            )

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error disconnecting from '{self.server.name}': {e}")
            self._session = None
            self._tools = []

    async def health_check(self) -> dict[str, Any]:
        """Check connection health."""
        return {
            "server_name": self.server.name,
            "connected": self._session is not None,
            "tools_count": len(self._tools),
        }


class MCPClientManager:
    """Manager for multiple MCP client connections."""

    _instance: "MCPClientManager | None" = None

    def __new__(cls) -> "MCPClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}
            cls._instance._servers = {}
        return cls._instance

    def __init__(self) -> None:
        # Ensure instance attributes exist (for singleton)
        if not hasattr(self, "_clients"):
            self._clients: dict[str, MCPClient] = {}
            self._servers: dict[str, MCPServer] = {}

    def register_server(self, server: MCPServer) -> None:
        """
        Register an MCP server configuration.

        Args:
            server: Server configuration to register
        """
        self._servers[server.name] = server
        logger.info(f"Registered MCP server '{server.name}'")

    async def connect_all(self) -> dict[str, bool]:
        """
        Connect to all registered and enabled servers.

        Returns:
            Dict of server_name -> success status
        """
        results: dict[str, bool] = {}
        for name, server in self._servers.items():
            if not server.enabled:
                logger.info(f"MCP server '{name}' is disabled, skipping")
                results[name] = False
                continue

            client = MCPClient(server)
            success = await client.connect()
            if success:
                self._clients[name] = client
            results[name] = success

        return results

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        for name, client in list(self._clients.items()):
            await client.disconnect()
            del self._clients[name]

    def get_client(self, server_name: str) -> MCPClient | None:
        """Get client for a specific server."""
        return self._clients.get(server_name)

    def list_all_tools(self) -> list[MCPTool]:
        """List all tools from all connected servers."""
        tools: list[MCPTool] = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        """
        Call a tool on a specific server.

        Args:
            server_name: Name of the server
            tool_name: Name of the tool
            arguments: Tool arguments

        Returns:
            ToolResult with output
        """
        client = self._clients.get(server_name)
        if not client:
            return ToolResult(
                tool_use_id="",
                content=f"Server '{server_name}' not connected",
                is_error=True,
            )
        return await client.call_tool(tool_name, arguments)

    async def health_check(self) -> dict[str, Any]:
        """Check health of all connections."""
        statuses: list[dict[str, Any]] = []
        for client in self._clients.values():
            status = await client.health_check()
            statuses.append(status)

        return {
            "status": "healthy" if statuses else "no_connections",
            "servers_registered": len(self._servers),
            "servers_connected": len(self._clients),
            "servers": statuses,
        }


def get_mcp_client_manager() -> MCPClientManager:
    """Get the global MCP client manager instance."""
    return MCPClientManager()


def clear_mcp_client_manager() -> None:
    """Clear the global client manager (for testing)."""
    MCPClientManager._instance = None
