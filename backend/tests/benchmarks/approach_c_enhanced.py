"""Approach C Enhanced: Auto-Claude with current runtime hooks in can_use_tool.

SDK manages the entire tool loop with generous max_turns.
can_use_tool callback enforces the current runtime hook stack:
  1. Project permission tier
  2. Cross-project path enforcement
MCP server with DirectToolExecutor handles custom tools.

Preserves: everything the SDK provides (caching, session, single subprocess).
Adds: current built-in tool parity without dead per-request permission config.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
from claude_agent_sdk import tool as sdk_tool
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    UserMessage,
)

from app.adapters._claude_constants import MCP_SERVER_NAME
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


def _build_mcp_server_with_executor(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
) -> Any:
    """Build MCP server with DirectToolExecutor (no permission checking).

    Permissions are enforced at the SDK level via can_use_tool callback,
    so the MCP handler itself doesn't need permission logic.
    """
    from app.services.tools.direct_executor_core import DirectToolExecutor

    executor = DirectToolExecutor(working_dir, project_id=project_id)
    mcp_tools = []

    for t in tools:
        tool_name = t["name"]

        async def handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            try:
                result = await executor.dispatch(_name, args)
                return {"content": [{"type": "text", "text": result}]}
            except Exception as e:
                logger.exception("MCP handler error: tool=%s", _name)
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(handler))

    return create_sdk_mcp_server(MCP_SERVER_NAME, tools=mcp_tools)


def _build_3_layer_can_use_tool(
    project_id: str | None,
    metrics_collector: dict[str, int],
) -> Any:
    """Build a can_use_tool callback with the current runtime hook stack."""
    from app.adapters.claude_tools_permissions import (
        compose_permission_hooks,
        make_can_use_tool_callback,
    )
    from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

    base_callback = make_can_use_tool_callback(compose_permission_hooks(project_id))

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        metrics_collector["permission_checks"] += 1
        result = await base_callback(tool_name, tool_input, context)
        if isinstance(result, PermissionResultDeny):
            metrics_collector["permission_denials"] += 1
        return result

    return can_use_tool


async def run_approach_c_enhanced(
    model: str,
    working_dir: str | None,
    project_id: str | None,
) -> BenchmarkResult:
    """SDK fully manages with current runtime hooks in can_use_tool."""
    result = BenchmarkResult(approach="C+", approach_name="Auto-Claude (Current Hooks)")
    cli_path = get_cli_path()
    metrics: dict[str, int] = {"permission_checks": 0, "permission_denials": 0}

    can_use_tool_cb = _build_3_layer_can_use_tool(
        project_id=project_id,
        metrics_collector=metrics,
    )

    mcp_server = _build_mcp_server_with_executor(
        tools=BENCHMARK_TOOLS,
        working_dir=working_dir,
        project_id=project_id,
    )

    options = ClaudeAgentOptions(
        cli_path=cli_path,
        model=model,
        cwd=working_dir or ".",
        can_use_tool=can_use_tool_cb,
        mcp_servers={"agent-hub": mcp_server},
        max_turns=50,
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
                        "C+: Turn %d — %d tool calls: %s",
                        turn_number, len(tool_calls),
                        [tc["name"] for tc in tool_calls],
                    )

                elif isinstance(message, UserMessage):
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
                        latency_ms=0,
                        tool_calls=list(current_turn_tools),
                        tool_results=list(current_turn_results),
                        permission_checks=metrics["permission_checks"],
                        permission_denials=metrics["permission_denials"],
                    ))

                elif isinstance(message, ResultMessage):
                    usage = extract_usage_from_result(message)
                    logger.info("C+: ResultMessage — turns=%s, cost=$%.6f, usage=%s",
                                getattr(message, "num_turns", "?"), usage["cost_usd"], usage)
                    result.total_cost_usd += usage["cost_usd"]
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
        logger.exception("Approach C+ error")

    result.total_latency_ms = timer.ms
    result.subprocess_count = 1
    result.peak_rss_mb = get_peak_rss_mb()
    result.permission_checks = metrics["permission_checks"]
    result.permission_denials = metrics["permission_denials"]
    result.aggregate_turns()
    result.correct = check_correctness(all_tool_calls)

    return result
