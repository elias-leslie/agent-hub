"""Shared utilities for benchmark implementations."""

from __future__ import annotations

import logging
import resource
import shutil
import time
from typing import Any

from claude_agent_sdk import tool as sdk_tool
from claude_agent_sdk.types import AssistantMessage, ResultMessage

logger = logging.getLogger(__name__)

# The benchmark test prompt. Instructs the model to perform sequential tool calls.
BENCHMARK_PROMPT = (
    "I need you to do three things in sequence:\n"
    "1. Use write_user_context to save: 'Benchmark user: prefers dark mode, uses Python 3.12'\n"
    "2. Use read_user_context to verify what was saved\n"
    "3. Use write_user_context to append: 'Benchmark user: prefers dark mode, uses Python 3.12, "
    "enjoys hiking on weekends'\n"
    "Do each step one at a time. After step 3, summarize what you did."
)

EXPECTED_TOOL_SEQUENCE = [
    "write_user_context",
    "read_user_context",
    "write_user_context",
]

# Tool definitions matching the production persona tools
BENCHMARK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "write_user_context",
        "description": (
            "Update your knowledge about the user. Record preferences, patterns, "
            "communication style, and other user-specific information you learn. "
            "This is cumulative — update with the full document each time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_context": {
                    "type": "string",
                    "description": "The updated user context document (markdown)",
                },
            },
            "required": ["user_context"],
        },
    },
    {
        "name": "read_user_context",
        "description": "Read your current knowledge about the user.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def get_cli_path() -> str:
    """Find the claude CLI binary. Raises if not found."""
    path = shutil.which("claude")
    if not path:
        msg = "claude CLI not found in PATH"
        raise RuntimeError(msg)
    return path


def get_peak_rss_mb() -> float:
    """Get peak RSS in MB from resource usage."""
    # ru_maxrss is in KB on Linux, bytes on macOS
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_maxrss / 1024  # KB → MB


def normalize_tool_name(name: str) -> str:
    """Strip MCP server prefix from tool names.

    SDK prepends 'mcp__<server>__' to MCP tool names, e.g.
    'mcp__agent-hub__write_user_context' → 'write_user_context'.
    """
    if name.startswith("mcp__"):
        # mcp__agent-hub__write_user_context → write_user_context
        parts = name.split("__", 2)
        if len(parts) == 3:
            return parts[2]
    return name


def extract_tool_calls_from_message(message: AssistantMessage) -> list[dict[str, Any]]:
    """Extract tool_use blocks from an AssistantMessage.

    Tool names are normalized (MCP prefix stripped).
    """
    tool_calls: list[dict[str, Any]] = []
    for block in message.content:
        block_type = type(block).__name__
        if block_type == "ToolUseBlock" or getattr(block, "type", None) == "tool_use":
            raw_name = getattr(block, "name", "")
            tool_calls.append({
                "id": getattr(block, "id", ""),
                "name": normalize_tool_name(raw_name),
                "input": getattr(block, "input", {}),
            })
    return tool_calls


def extract_usage_from_result(result: ResultMessage) -> dict[str, Any]:
    """Extract token usage and cost from a ResultMessage.

    ResultMessage.usage is a dict[str, Any], not an object.
    ResultMessage.total_cost_usd is a float.
    """
    usage = result.usage
    cost = result.total_cost_usd or 0.0
    if not usage:
        return {
            "input_tokens": 0, "output_tokens": 0,
            "cache_read": 0, "cache_creation": 0,
            "cost_usd": cost,
        }
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_creation": usage.get("cache_creation_input_tokens", 0) or 0,
        "cost_usd": cost,
    }


def check_correctness(tool_calls_observed: list[str]) -> bool:
    """Check if observed tool calls match expected sequence."""
    if len(tool_calls_observed) < len(EXPECTED_TOOL_SEQUENCE):
        return False
    # Check that expected tools appear in order (may have extras)
    idx = 0
    for call in tool_calls_observed:
        if idx < len(EXPECTED_TOOL_SEQUENCE) and call == EXPECTED_TOOL_SEQUENCE[idx]:
            idx += 1
    return idx == len(EXPECTED_TOOL_SEQUENCE)


def build_mcp_tools_for_benchmark(
    executor_fn: Any,
) -> list[Any]:
    """Build MCP tool wrappers for benchmark tools using a provided executor function.

    Args:
        executor_fn: async callable(tool_name, args) -> str
    """
    mcp_tools = []
    for t in BENCHMARK_TOOLS:
        tool_name = t["name"]

        async def handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            try:
                result = await executor_fn(_name, args)
                return {"content": [{"type": "text", "text": result}]}
            except Exception as e:
                logger.exception("MCP handler error: tool=%s", _name)
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(handler))
    return mcp_tools


async def stream_prompt(prompt: str) -> Any:
    """Wrap a prompt string as an async iterable for SDK streaming mode."""

    async def _gen():
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _gen()


class Timer:
    """Simple context-manager timer."""

    def __init__(self) -> None:
        self.start_ns: int = 0
        self.end_ns: int = 0

    def __enter__(self) -> Timer:
        self.start_ns = time.monotonic_ns()
        return self

    def __exit__(self, *_: Any) -> None:
        self.end_ns = time.monotonic_ns()

    @property
    def ms(self) -> int:
        return int((self.end_ns - self.start_ns) / 1_000_000)
