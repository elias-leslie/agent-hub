"""Approach A: MCP + DirectToolHandler (Permission Fix).

SDK manages the tool loop in a single subprocess.
MCP handler routes through DirectToolHandler (with permission checking)
instead of DirectToolExecutor (no permission checking).
can_use_tool callback handles CLI builtins; MCP handler handles custom tools.

Preserves: prompt caching, session continuity, single subprocess.
Adds: current runtime boundary enforcement on custom tools via DirectToolHandler.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
from claude_agent_sdk import tool as sdk_tool
from claude_agent_sdk.types import AssistantMessage, ResultMessage, UserMessage

from app.services.mcp_constants import MCP_SERVER_NAME
from tests.benchmarks._shared import (
    BENCHMARK_PROMPT,
    BENCHMARK_TOOLS,
    Timer,
    check_correctness,
    extract_tool_calls_from_message,
    extract_usage_from_result,
    get_cli_path,
    get_peak_rss_mb,
    stream_prompt,
)
from tests.benchmarks.models import BenchmarkResult, TurnMetrics

logger = logging.getLogger(__name__)


def _build_mcp_server_with_handler(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
    metrics_collector: dict[str, int],
) -> Any:
    """Build MCP server backed by DirectToolHandler (with permissions).

    This is the key difference from production: instead of DirectToolExecutor
    (no permissions), we use create_direct_handler which composes 3 permission
    layers: project tier plus cross-project/checkout boundaries.
    """
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir=working_dir,
        project_id=project_id,
    )

    from app.services.tools.base import ToolCall

    mcp_tools = []
    for t in tools:
        tool_name = t["name"]

        async def mcp_handler(
            args: dict[str, Any],
            _name: str = tool_name,
        ) -> dict[str, Any]:
            metrics_collector["permission_checks"] += 1
            tool_call = ToolCall(id="bench", name=_name, input=args)
            result = await handler.execute(tool_call)
            if result.is_error:
                metrics_collector["permission_denials"] += 1
                return {
                    "content": [{"type": "text", "text": result.content}],
                    "is_error": True,
                }
            return {"content": [{"type": "text", "text": result.content}]}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(mcp_handler))

    return create_sdk_mcp_server(MCP_SERVER_NAME, tools=mcp_tools)


async def run_approach_a(
    model: str,
    working_dir: str | None,
    project_id: str | None,
) -> BenchmarkResult:
    """SDK-managed loop with DirectToolHandler in MCP handler."""
    result = BenchmarkResult(approach="A", approach_name="MCP + DirectToolHandler")
    cli_path = get_cli_path()
    metrics: dict[str, int] = {"permission_checks": 0, "permission_denials": 0}

    mcp_server = _build_mcp_server_with_handler(
        tools=BENCHMARK_TOOLS,
        working_dir=working_dir,
        project_id=project_id,
        metrics_collector=metrics,
    )

    options = ClaudeAgentOptions(
        cli_path=cli_path,
        model=model,
        cwd=working_dir or ".",
        permission_mode="bypassPermissions",
        mcp_servers={"agent-hub": mcp_server},
        max_turns=10,
        max_budget_usd=1.0,
        allowed_tools=[],
    )

    all_tool_calls: list[str] = []
    turn_number = 0
    current_turn_tools: list[str] = []
    current_turn_results: list[str] = []

    timer = Timer()
    try:
        with timer:
            prompt = await stream_prompt(BENCHMARK_PROMPT)
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    turn_number += 1
                    current_turn_tools = []
                    current_turn_results = []
                    tool_calls = extract_tool_calls_from_message(message)
                    for tc in tool_calls:
                        current_turn_tools.append(tc["name"])
                        all_tool_calls.append(tc["name"])
                    logger.info(
                        "A: Turn %d — %d tool calls: %s",
                        turn_number, len(tool_calls),
                        [tc["name"] for tc in tool_calls],
                    )

                elif isinstance(message, UserMessage):
                    # Tool results from MCP handler
                    if hasattr(message, "content"):
                        for block in message.content:
                            block_type = type(block).__name__
                            if block_type == "ToolResultBlock" or getattr(block, "type", None) == "tool_result":
                                content = str(getattr(block, "content", ""))[:100]
                                is_error = getattr(block, "is_error", False)
                                current_turn_results.append(
                                    f"{'ERROR: ' if is_error else ''}{content}"
                                )

                    result.turns.append(TurnMetrics(
                        turn_number=turn_number,
                        latency_ms=0,  # Can't measure per-turn in single-subprocess
                        tool_calls=list(current_turn_tools),
                        tool_results=list(current_turn_results),
                        permission_checks=metrics["permission_checks"],
                        permission_denials=metrics["permission_denials"],
                    ))

                elif isinstance(message, ResultMessage):
                    usage = extract_usage_from_result(message)
                    num_turns = getattr(message, "num_turns", turn_number)
                    logger.info(
                        "A: ResultMessage — turns=%s, cost=$%.6f, usage=%s",
                        num_turns, usage["cost_usd"], usage,
                    )
                    result.total_cost_usd += usage["cost_usd"]
                    # Apply usage to last turn or create summary turn
                    if result.turns:
                        last_turn = result.turns[-1]
                        last_turn.input_tokens = usage["input_tokens"]
                        last_turn.output_tokens = usage["output_tokens"]
                        last_turn.cache_read_tokens = usage["cache_read"]
                        last_turn.cache_creation_tokens = usage["cache_creation"]
                    else:
                        result.turns.append(TurnMetrics(
                            turn_number=1,
                            latency_ms=0,
                            input_tokens=usage["input_tokens"],
                            output_tokens=usage["output_tokens"],
                            cache_read_tokens=usage["cache_read"],
                            cache_creation_tokens=usage["cache_creation"],
                        ))

    except Exception as e:
        result.errors.append(f"SDK error: {e}")
        logger.exception("Approach A error")

    result.total_latency_ms = timer.ms
    result.subprocess_count = 1
    result.peak_rss_mb = get_peak_rss_mb()
    result.permission_checks = metrics["permission_checks"]
    result.permission_denials = metrics["permission_denials"]
    result.aggregate_turns()
    result.correct = check_correctness(all_tool_calls)

    return result
