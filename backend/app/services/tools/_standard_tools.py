"""Standard tool definitions used by most agents."""

from __future__ import annotations

from app.services.tools._executor_precision_code_search import (
    DEFAULT_PRECISION_SEARCH_BUDGET,
)
from app.services.tools._executor_web import (
    DEFAULT_WEB_FETCH_MAX_CHARS,
    DEFAULT_WEB_SEARCH_RESULTS,
    MAX_WEB_FETCH_MAX_CHARS,
    MAX_WEB_SEARCH_RESULTS,
)
from app.services.tools._tool_constants import DEFAULT_READ_LIMIT, DEFAULT_TIMEOUT
from app.services.tools.base import Tool

BASH_TOOL = Tool(
    name="bash",
    description=(
        "Execute a bash command in the working directory. "
        "Use for running tests, git operations, or system commands. "
        "Do not use bash/curl for ordinary public-web research when "
        "`search_web` or `fetch_web_page` can do the job. Never call the "
        "`web-research` shell wrapper from Agent Hub bash; that wrapper is for "
        "shell-only clients."
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
        "Consult another agent for expert review, a second opinion, or strategic guidance. "
        "Consultations can use read-only research tools such as `read_file`, "
        "`precision_code_search`, `search_web`, and `fetch_web_page`, but not bash, writes, "
        "or autonomous dispatch. Check direct sources first. Do not use it for exact rule text "
        "or file/project facts you can retrieve with `st memory get/search`, `read_file`, or "
        "search tools. Your agent roster shows available agents. Use consult_agent for bounded "
        "advice; use dispatch_agent to run an agent with full tool access."
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
    usage_examples=["Ask the reviewer agent for risk-focused feedback after inspecting the code."],
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

SEARCH_WEB_TOOL = Tool(
    name="search_web",
    description=(
        "Search the public web for current information and candidate sources. "
        "Use this for research, inspiration, or to find pages to inspect before "
        "calling `fetch_web_page`. Prefer this over bash/curl or provider-native "
        "web tools for ordinary public-web research. When this tool is available, "
        "call it directly instead of routing through bash wrappers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for the public web.",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of results to return "
                    f"(default {DEFAULT_WEB_SEARCH_RESULTS}, max {MAX_WEB_SEARCH_RESULTS})."
                ),
                "default": DEFAULT_WEB_SEARCH_RESULTS,
            },
            "search_type": {
                "type": "string",
                "description": "Search scope: `text` for general search or `news` for recent news.",
                "enum": ["text", "news"],
                "default": "text",
            },
            "timelimit": {
                "type": "string",
                "description": "Optional time filter: `d`, `w`, `m`, or `y`.",
                "enum": ["d", "w", "m", "y"],
            },
        },
        "required": ["query"],
    },
    category="web",
    search_keywords=["internet research", "browse web", "current information", "find sources"],
    usage_examples=[
        "Search for recent competitor launches before comparing their landing pages.",
    ],
)

FETCH_WEB_PAGE_TOOL = Tool(
    name="fetch_web_page",
    description=(
        "Fetch a webpage and extract readable content. "
        "Use this after `search_web` or when you already have a URL and need the page text. "
        "Prefer this over bash/curl for public webpage retrieval. For large pages, "
        "pass `focus_query` to return the most relevant sections. When this tool is "
        "available, call it directly instead of routing through bash wrappers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to fetch.",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    "Maximum number of content characters to return "
                    f"(default {DEFAULT_WEB_FETCH_MAX_CHARS}, max {MAX_WEB_FETCH_MAX_CHARS})."
                ),
                "default": DEFAULT_WEB_FETCH_MAX_CHARS,
            },
            "focus_query": {
                "type": "string",
                "description": (
                    "Optional research question or target topic for large pages. "
                    "When provided, the tool focuses the response on the most relevant sections "
                    "before truncation."
                ),
            },
        },
        "required": ["url"],
    },
    category="web",
    search_keywords=["open url", "read webpage", "extract article", "fetch site content"],
    usage_examples=[
        "Fetch the top result from `search_web` to inspect the actual article text.",
        "Use `focus_query` when a long page only matters for one topic or field.",
    ],
)

STANDARD_TOOLS: list[Tool] = [
    BASH_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    CONSULT_AGENT_TOOL,
    PRECISION_CODE_SEARCH_TOOL,
    SEARCH_WEB_TOOL,
    FETCH_WEB_PAGE_TOOL,
]


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()
