"""Standard tool definitions used by most agents."""

from __future__ import annotations

from app.services.tools._executor_precision_code_search import (
    DEFAULT_PRECISION_SEARCH_BUDGET,
)
from app.services.tools._tool_constants import DEFAULT_READ_LIMIT, DEFAULT_TIMEOUT
from app.services.tools.base import Tool

BASH_TOOL = Tool(
    name="bash",
    description=(
        "Execute a bash command in the working directory. "
        "Use for running tests, git operations, or system commands."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": f"Timeout in seconds (default {DEFAULT_TIMEOUT})",
                "default": DEFAULT_TIMEOUT,
            },
        },
        "required": ["command"],
    },
    category="workspace",
    search_keywords=["shell", "command", "test", "git"],
    usage_examples=["Run the changed-file quality gate with `dt -q -d`."],
)

READ_FILE_TOOL = Tool(
    name="read_file",
    description="Read contents of a file. Returns lines with line numbers.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (absolute or relative to working directory)",
            },
            "offset": {
                "type": "integer",
                "description": "Line offset to start reading from (0-indexed)",
                "default": 0,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
                "default": DEFAULT_READ_LIMIT,
            },
        },
        "required": ["path"],
    },
    category="workspace",
    search_keywords=["inspect file", "open file", "source code"],
    usage_examples=["Read a backend module before editing it."],
)

WRITE_FILE_TOOL = Tool(
    name="write_file",
    description="Write content to a file. Creates parent directories if needed.",
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (absolute or relative to working directory)",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
        },
        "required": ["path", "content"],
    },
    category="workspace",
    search_keywords=["edit file", "write patch"],
    usage_examples=["Update a source file after validating the target lines."],
)

CONSULT_AGENT_TOOL = Tool(
    name="consult_agent",
    description=(
        "Consult another agent for text-only advice (no tool execution). Use when you "
        "need expert review, a second opinion, or strategic guidance. "
        "Your agent roster shows available agents. "
        "Use consult_agent for advice; use dispatch_agent to run an agent with full tool access."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "The agent to consult (e.g., 'supervisor', 'reviewer')",
            },
            "question": {
                "type": "string",
                "description": "The question or problem to get help with",
            },
            "context": {
                "type": "string",
                "description": "Additional context about the current situation",
                "default": "",
            },
        },
        "required": ["agent_slug", "question"],
    },
    category="agents",
    search_keywords=["second opinion", "review", "strategy"],
    usage_examples=["Ask the reviewer agent for risk-focused feedback."],
)

PRECISION_CODE_SEARCH_TOOL = Tool(
    name="precision_code_search",
    description=(
        "Retrieve focused code context for symbol and implementation lookup. "
        "Use this before broad file search when you need functions, classes, "
        "components, handlers, endpoints, schemas, or where something is implemented."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Code-navigation query or symbol name to retrieve",
            },
            "budget": {
                "type": "integer",
                "description": f"Approximate token budget for returned context (default {DEFAULT_PRECISION_SEARCH_BUDGET})",
                "default": DEFAULT_PRECISION_SEARCH_BUDGET,
            },
        },
        "required": ["query"],
    },
    category="workspace",
    search_keywords=["symbol search", "implementation lookup", "code navigation", "find handler"],
    usage_examples=["Look up `get_file_tree` before reading whole files."],
)

STANDARD_TOOLS: list[Tool] = [
    BASH_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    CONSULT_AGENT_TOOL,
    PRECISION_CODE_SEARCH_TOOL,
]


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()
