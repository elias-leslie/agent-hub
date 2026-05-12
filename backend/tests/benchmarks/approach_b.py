"""Approach B: Deny-All + Our Tool Loop (Full Unification).

SDK used for single-turn completion only (max_turns=1, can_use_tool denies all).
Our code executes tools via DirectToolHandler, builds messages, re-calls SDK per turn.

Eliminates: MCP execution, race conditions, dual code paths.
Costs: one subprocess per turn, no cross-turn caching, context rebuild.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
from claude_agent_sdk import tool as sdk_tool
from claude_agent_sdk.types import (
    AssistantMessage,
    PermissionResultDeny,
    ResultMessage,
    ToolPermissionContext,
)

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

MAX_LOOP_TURNS = 10


def _build_mcp_for_visibility() -> Any:
    """Build MCP server for tool visibility only (tools are NOT executed here)."""
    mcp_tools = []
    for t in BENCHMARK_TOOLS:
        tool_name = t["name"]

        async def noop_handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            # Should never be called since can_use_tool denies all
            logger.error("MCP handler called despite deny-all! tool=%s", _name)
            return {"content": [{"type": "text", "text": "ERROR: should not execute"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(noop_handler))

    return create_sdk_mcp_server(MCP_SERVER_NAME, tools=mcp_tools)


async def _single_turn_query(
    prompt_text: str,
    options: ClaudeAgentOptions,
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    """Run a single SDK turn and extract tool_use blocks + usage.

    Returns:
        (tool_calls, usage_dict, has_text_response)
    """
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_creation": 0}
    has_text = False

    prompt = await stream_prompt(prompt_text)
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            extracted = extract_tool_calls_from_message(message)
            tool_calls.extend(extracted)
            # Check for text content (final response)
            for block in message.content:
                block_type = type(block).__name__
                if block_type == "TextBlock" or getattr(block, "type", None) == "text":
                    text = getattr(block, "text", "")
                    if text.strip():
                        has_text = True

        elif isinstance(message, ResultMessage):
            usage = extract_usage_from_result(message)

    return tool_calls, usage, has_text


async def run_approach_b(
    model: str,
    working_dir: str | None,
    project_id: str | None,
) -> BenchmarkResult:
    """SDK single-turn + our DirectToolHandler loop."""
    result = BenchmarkResult(approach="B", approach_name="Deny-All + Our Tool Loop")
    cli_path = get_cli_path()

    # Build handler with full permission stack
    from app.services.tools.base import ToolCall
    from app.services.tools.tool_handler import create_direct_handler

    handler = create_direct_handler(
        working_dir=working_dir,
        project_id=project_id,
    )

    # Deny-all callback for SDK
    deny_count = 0

    async def deny_all(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultDeny:
        nonlocal deny_count
        deny_count += 1
        return PermissionResultDeny(message=f"Tool '{tool_name}' denied (benchmark deny-all)")

    mcp_server = _build_mcp_for_visibility()
    permission_checks = 0
    permission_denials = 0
    all_tool_calls: list[str] = []
    subprocess_count = 0

    # Build conversation as explicit assistant/user turns so model sees progress
    # Format: User prompt → Assistant called tool X → Tool returned Y → ...
    conversation_history: list[str] = []
    total_timer = Timer()

    try:
        with total_timer:
            for turn in range(1, MAX_LOOP_TURNS + 1):
                turn_timer = Timer()

                options = ClaudeAgentOptions(
                    cli_path=cli_path,
                    model=model,
                    cwd=working_dir or ".",
                    can_use_tool=deny_all,
                    mcp_servers={"agent-hub": mcp_server},
                    max_turns=1,
                    max_budget_usd=1.0,
                    allowed_tools=[],
                )
                subprocess_count += 1

                # Build prompt: original request + conversation history showing completed steps
                if conversation_history:
                    prompt_text = (
                        f"User: {BENCHMARK_PROMPT}\n\n"
                        + "\n\n".join(conversation_history)
                        + "\n\nAssistant: "
                    )
                else:
                    prompt_text = BENCHMARK_PROMPT

                with turn_timer:
                    tool_calls, usage, _has_text = await _single_turn_query(prompt_text, options)

                result.total_cost_usd += usage.get("cost_usd", 0.0)
                turn_tools: list[str] = [tc["name"] for tc in tool_calls]
                turn_results: list[str] = []

                if not tool_calls:
                    # Model responded with text only — done
                    result.turns.append(TurnMetrics(
                        turn_number=turn,
                        latency_ms=turn_timer.ms,
                        input_tokens=usage["input_tokens"],
                        output_tokens=usage["output_tokens"],
                        cache_read_tokens=usage["cache_read"],
                        cache_creation_tokens=usage["cache_creation"],
                        tool_calls=[],
                        tool_results=[],
                    ))
                    logger.info("B: Turn %d — no tool calls, finishing", turn)
                    break

                # Execute tools via our handler
                for tc in tool_calls:
                    permission_checks += 1
                    all_tool_calls.append(tc["name"])

                    tool_call = ToolCall(id=tc["id"], name=tc["name"], input=tc["input"])
                    tool_result = await handler.execute(tool_call)

                    if tool_result.is_error:
                        permission_denials += 1

                    turn_results.append(
                        f"{'ERROR: ' if tool_result.is_error else ''}{tool_result.content[:100]}"
                    )

                    # Add to conversation history as explicit assistant action + result
                    input_summary = str(tc["input"])[:200]
                    conversation_history.append(
                        f"Assistant: [Called {tc['name']}({input_summary})]\n"
                        f"Tool result: {tool_result.content}"
                    )

                result.turns.append(TurnMetrics(
                    turn_number=turn,
                    latency_ms=turn_timer.ms,
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    cache_read_tokens=usage["cache_read"],
                    cache_creation_tokens=usage["cache_creation"],
                    tool_calls=turn_tools,
                    tool_results=turn_results,
                    permission_checks=permission_checks,
                    permission_denials=permission_denials,
                ))

                logger.info(
                    "B: Turn %d — tools: %s, latency: %dms",
                    turn, turn_tools, turn_timer.ms,
                )

    except Exception as e:
        result.errors.append(f"Loop error: {e}")
        logger.exception("Approach B error")

    result.total_latency_ms = total_timer.ms
    result.subprocess_count = subprocess_count
    result.peak_rss_mb = get_peak_rss_mb()
    result.permission_checks = permission_checks
    result.permission_denials = permission_denials
    result.aggregate_turns()
    result.correct = check_correctness(all_tool_calls)

    return result
