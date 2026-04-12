"""Approach C Enhanced: Auto-Claude with full 3-layer permissions in can_use_tool.

SDK manages the entire tool loop with generous max_turns.
can_use_tool callback enforces ALL 3 permission layers (not just PermissionChecker):
  1. Project permission tier (off/read/write/yolo)
  2. Cross-project path enforcement
  3. Per-request PermissionConfig (granular allow/deny)
MCP server with DirectToolExecutor handles custom tools (no handler overhead).

Preserves: everything the SDK provides (caching, session, single subprocess).
Adds: full permission parity with DirectToolHandler, enforced at SDK level.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
from claude_agent_sdk import tool as sdk_tool
from claude_agent_sdk.types import (
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    ToolPermissionContext,
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
    permission_config: dict[str, Any] | None,
    metrics_collector: dict[str, int],
) -> Any:
    """Build a can_use_tool callback with all 3 permission layers.

    Reuses the same hook functions from tool_handler.py to ensure
    parity with DirectToolHandler's permission enforcement.
    """
    from app.services.tools.base import ToolCall, ToolDecision
    from app.services.tools.tool_handler import (
        _compose_hooks,
        _create_cross_project_permission_hook,
        _create_project_permission_hook,
    )
    from tests.benchmarks._shared import normalize_tool_name

    # Compose the same 3 layers as create_direct_handler
    hooks = []

    if project_id:
        hooks.append(_create_project_permission_hook(project_id))

    if project_id:
        hooks.append(_create_cross_project_permission_hook(project_id))

    if permission_config:
        from app.services.tools.permissions import PermissionChecker, PermissionConfig

        config = PermissionConfig.from_dict(permission_config)
        checker = PermissionChecker(config)
        hooks.append(checker.create_hook())

    composed_hook = _compose_hooks(hooks) if len(hooks) > 1 else (hooks[0] if hooks else None)

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        metrics_collector["permission_checks"] += 1

        if composed_hook is None:
            return PermissionResultAllow()

        # SDK passes MCP-prefixed names (mcp__agent-hub__write_user_context).
        # Permission hooks expect unprefixed names (write_user_context).
        normalized_name = normalize_tool_name(tool_name)
        tool_call = ToolCall(id="", name=normalized_name, input=tool_input)
        decision = await composed_hook(tool_call)

        if decision == ToolDecision.DENY:
            metrics_collector["permission_denials"] += 1
            return PermissionResultDeny(message=f"Tool '{tool_name}' denied by permission policy")
        return PermissionResultAllow()

    return can_use_tool


async def run_approach_c_enhanced(
    model: str,
    working_dir: str | None,
    project_id: str | None,
    permission_config: dict[str, Any] | None,
) -> BenchmarkResult:
    """SDK fully manages with 3-layer can_use_tool for full permission enforcement."""
    result = BenchmarkResult(approach="C+", approach_name="Auto-Claude (3-Layer Permissions)")
    cli_path = get_cli_path()
    metrics: dict[str, int] = {"permission_checks": 0, "permission_denials": 0}

    can_use_tool_cb = _build_3_layer_can_use_tool(
        project_id=project_id,
        permission_config=permission_config,
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
