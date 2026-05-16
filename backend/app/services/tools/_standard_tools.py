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
from app.services.tools._tool_constants import DEFAULT_READ_LIMIT
from app.services.tools.base import Tool

BASH_TOOL = Tool(
    name="bash",
    description=(
        "Execute a bash command in the working directory. "
        "Use for running tests, version-control operations, system commands, and canonical "
        "project wrappers such as `st`. "
        "Prefer wrapper CLIs over ad hoc raw commands when wrappers already exist."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            },
        },
        "required": ["command"],
    },
    category="workspace",
    search_keywords=["shell", "command", "test", "git"],
    usage_examples=["Run the changed-file quality gate with `st check --quick --changed-only`."],
)

SEARCH_SCRATCH_CONTEXT_TOOL = Tool(
    name="search_scratch_context",
    description=(
        "Search full output previously indexed from oversized bash or batch results. "
        "Use when a tool returned a scratch artifact id instead of full output."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Term or phrase to find in scratch artifacts",
            },
            "artifact_id": {
                "type": "string",
                "description": "Optional scratch artifact id; omit to search current session artifacts",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum matches to return",
                "default": 5,
            },
            "context_lines": {
                "type": "integer",
                "description": "Neighboring lines around each match",
                "default": 2,
            },
        },
        "required": ["query"],
    },
    category="workspace",
    search_keywords=["scratch", "large output", "indexed output", "search previous command"],
    usage_examples=["Search a large test log artifact for the failing test name."],
)

BATCH_EXECUTE_TOOL = Tool(
    name="batch_execute",
    description=(
        "Run up to 8 bash commands sequentially. Large command outputs are indexed as "
        "scratch artifacts and returned as compact searchable handles."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 8,
                "description": "Bash commands to execute in order",
            },
            "stop_on_error": {
                "type": "boolean",
                "description": "Stop after the first blocked or error result",
                "default": True,
            },
        },
        "required": ["commands"],
    },
    category="workspace",
    search_keywords=["batch", "many commands", "large output", "indexed output"],
    usage_examples=["Run several inspection commands and index any large logs."],
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

EDIT_FILE_TOOL = Tool(
    name="edit_file",
    description=(
        "Edit an existing file by replacing exact old_text with new_text. "
        "Use this for targeted source changes, especially in large files."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (absolute or relative to working directory)",
            },
            "old_text": {
                "type": "string",
                "description": "Exact text to replace. Include enough surrounding context to make it unique.",
            },
            "new_text": {
                "type": "string",
                "description": "Replacement text",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all matches. Default false rejects ambiguous old_text.",
                "default": False,
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
    category="workspace",
    search_keywords=["edit file", "replace text", "patch"],
    usage_examples=["Replace one focused function body after reading the target lines."],
)

WRITE_FILE_TOOL = Tool(
    name="write_file",
    description=(
        "Write content to a file. Creates parent directories if needed. "
        "For existing large source files, prefer edit_file; destructive large truncation is blocked "
        "unless allow_large_truncate=true is intentional."
    ),
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
            "allow_large_truncate": {
                "type": "boolean",
                "description": "Permit intentional whole-file replacement that greatly shrinks a large existing file.",
                "default": False,
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
        "search tools. Your agent roster shows available agents. Use consult_agent only for "
        "bounded advice; use bash with `st` for project work and orchestration."
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
        "When this tool is explicitly provisioned, use it for functions, classes, "
        "components, handlers, endpoints, schemas, or implementation lookup. "
        "In shell-first coding lanes, prefer `bash` with `st search`."
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

RESEARCH_WEB_TOOL = Tool(
    name="research_web",
    description=(
        "Run a one-call public-web research pass: search the web, pick a result, and fetch "
        "readable page content. Prefer this for ordinary query-based research when you need "
        "both discovery and source verification with fewer tool calls. Use `search_web` and "
        "`fetch_web_page` separately only when you need manual control over search and fetch steps."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Research query for the public web.",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of search results to consider "
                    f"(default {DEFAULT_WEB_SEARCH_RESULTS}, max {MAX_WEB_SEARCH_RESULTS})."
                ),
                "default": DEFAULT_WEB_SEARCH_RESULTS,
            },
            "result_index": {
                "type": "integer",
                "description": "1-based search result rank to fetch after searching.",
                "default": 1,
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
            "max_chars": {
                "type": "integer",
                "description": (
                    "Maximum number of fetched content characters to return "
                    f"(default {DEFAULT_WEB_FETCH_MAX_CHARS}, max {MAX_WEB_FETCH_MAX_CHARS})."
                ),
                "default": DEFAULT_WEB_FETCH_MAX_CHARS,
            },
            "focus_query": {
                "type": "string",
                "description": (
                    "Optional topic or question used to focus the fetched page. "
                    "Defaults to the research query for concise retrieval."
                ),
            },
        },
        "required": ["query"],
    },
    category="web",
    search_keywords=["web research", "search then fetch", "current info with source", "browse and verify"],
    usage_examples=[
        "Research a public topic with one tool call before deciding or dispatching follow-on work.",
    ],
)

SEARCH_WEB_TOOL = Tool(
    name="search_web",
    description=(
        "Search the public web for current information and candidate sources. "
        "Use this when you need manual search control or multiple candidate sources before "
        "calling `fetch_web_page`. For the common search-plus-fetch flow, prefer `research_web`. "
        "This is for explicitly provisioned research profiles; in shell-first coding lanes, "
        "prefer `bash` with `web-research`."
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
        "Use this when you already have a URL or need manual fetch control after `search_web`. "
        "For ordinary query-based research, prefer `research_web`. For large pages, pass "
        "`focus_query` to return the most relevant sections. This is for explicitly provisioned "
        "research profiles; in shell-first coding lanes, prefer `bash` with `web-research`."
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

PROPOSE_THOROUGH_TOOL = Tool(
    name="propose_thorough",
    description=(
        "Recommend the Thorough research mode (wider read + forced critique pass + "
        "revision). Call this when the question would benefit from a more exhaustive "
        "search and a self-review pass — e.g. the user asks for 'comprehensive', "
        "'deep dive', or 'every angle' coverage. Returns a structured JSON "
        "recommendation that the consumer surfaces to the user as a mode prompt."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "One-sentence justification for upgrading to Thorough.",
            },
        },
        "required": ["reason"],
    },
    category="research",
    search_keywords=["mode recommendation", "thorough research", "deep dive"],
    usage_examples=[
        "Recommend Thorough mode for an exhaustive cross-source synthesis question.",
    ],
)

PROPOSE_COMMITTEE_TOOL = Tool(
    name="propose_committee",
    description=(
        "Recommend the Committee research mode (skeptic / optimist / methodologist / "
        "domain-expert debate, with a judge consensus loop). Call this when the "
        "question is genuinely contested or the user asks to 'debate', 'weigh pros "
        "and cons', or seeks 'multiple perspectives'. Returns a structured JSON "
        "recommendation that the consumer surfaces to the user as a mode prompt."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "One-sentence justification for engaging the Committee.",
            },
        },
        "required": ["reason"],
    },
    category="research",
    search_keywords=["mode recommendation", "committee debate", "multiple perspectives"],
    usage_examples=[
        "Recommend Committee mode when the user asks to debate a contested claim.",
    ],
)

PROPOSE_HONING_TOOL = Tool(
    name="propose_honing",
    description=(
        "Recommend the Honing (karpathy-loop) research mode for iteratively "
        "optimizing an editable artifact (prompt, code, plan) against a measurable "
        "metric (judge rubric or test harness). REFUSES unless BOTH `editable_asset` "
        "(with path + kind) AND `metric` (with kind + spec) are fully specified; "
        "when incomplete, returns a fallback recommendation to Thorough mode with "
        "the missing slots listed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "editable_asset": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "kind": {"type": "string"},
                    "current_content": {"type": "string"},
                },
            },
            "metric": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["judge", "harness"]},
                    "spec": {"type": "object"},
                },
            },
            "hypothesis": {"type": "string"},
            "reason": {"type": "string"},
        },
    },
    category="research",
    search_keywords=[
        "mode recommendation",
        "honing",
        "karpathy loop",
        "metric-driven optimization",
    ],
    usage_examples=[
        "Recommend Honing only when the user has explicitly named both a metric and an asset to optimize.",
    ],
)


START_RESEARCH_TOOL = Tool(
    name="start_research",
    description=(
        "Hand off the conversation to the research loop. Call this when you have "
        "enough context to write a useful research brief. The `brief` should be a "
        "self-contained restatement of the user's goal in third person, including any "
        "constraints, angles, or output preferences they named. Optionally hint a `mode` "
        "if the brief clearly fits one — otherwise leave it out and the consumer will route."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "brief": {
                "type": "string",
                "description": "Refined, self-contained research prompt.",
            },
            "mode": {
                "type": "string",
                "enum": ["standard", "thorough", "committee", "honing"],
                "description": "Optional mode hint. Omit if unsure; the consumer will pick.",
            },
        },
        "required": ["brief"],
    },
    category="research",
    search_keywords=["start research", "intake handoff", "scoping complete"],
    usage_examples=[
        "Call when the user has answered enough to write a useful research brief.",
    ],
)


STANDARD_TOOLS: list[Tool] = [
    BASH_TOOL,
    READ_FILE_TOOL,
    EDIT_FILE_TOOL,
    WRITE_FILE_TOOL,
    SEARCH_SCRATCH_CONTEXT_TOOL,
]


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()
