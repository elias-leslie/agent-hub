"""Stdio MCP server exposing Agent Hub's standard coding tools (bash, read_file, edit_file, write_file).

Arm D only: lets the unmodified claude CLI drive Agent Hub's own tool implementations, with its built-in
tools switched off. The working directory is the step's worktree (the server's cwd).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

import mcp.types as types  # noqa: E402
from mcp.server.lowlevel import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

from app.services.tools.base import ToolCall, ToolCaller  # noqa: E402
from app.services.tools.catalog import build_tool_catalog  # noqa: E402
from app.services.tools.direct_executor import get_standard_tools  # noqa: E402
from app.services.tools.tool_handler import create_direct_handler  # noqa: E402

TOOLS = {"bash", "read_file", "edit_file", "write_file"}
WORKDIR = os.environ.get("AH_TOOL_WORKDIR") or os.getcwd()
CATALOG = [t for t in build_tool_catalog(get_standard_tools()) if t["name"] in TOOLS]
server = Server("ah")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"]) for t in CATALOG]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> types.CallToolResult:
    result = await HANDLER.execute(ToolCall(id=name, name=name, input=dict(arguments or {}), caller=ToolCaller(type="direct")))
    return types.CallToolResult(content=[types.TextContent(type="text", text=result.content)], isError=bool(result.is_error))


async def main() -> None:
    global HANDLER
    from app.constants.projects import refresh_project_cache

    await refresh_project_cache()  # the handler confines tools to known project roots and scratch
    HANDLER = create_direct_handler(working_dir=WORKDIR)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
