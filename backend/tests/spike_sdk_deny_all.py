"""Spike test: Validate Claude Agent SDK behavior with max_turns=1 + deny-all.

Tests the core assumption of the unified tool execution refactor:
  When max_turns=1 and can_use_tool denies all tools, the SDK should:
  1. Yield AssistantMessage with tool_use blocks (model sees tools via MCP)
  2. NOT execute the tools (denied by callback)
  3. Yield ResultMessage and stop

Run: cd backend && python -m tests.spike_sdk_deny_all
"""

import asyncio
import logging
import shutil
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    cli_path = shutil.which("claude")
    if not cli_path:
        print("FAIL: claude CLI not found")
        return

    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query
    from claude_agent_sdk import tool as sdk_tool
    from claude_agent_sdk.types import (
        AssistantMessage,
        PermissionResultDeny,
        ResultMessage,
        ToolPermissionContext,
        UserMessage,
    )

    # --- Build deny-all callback ---
    deny_count = 0

    async def deny_all_tools(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultDeny:
        nonlocal deny_count
        deny_count += 1
        logger.info(f"DENY #{deny_count}: tool={tool_name}, input_keys={list(tool_input.keys())}")
        return PermissionResultDeny(message=f"Tool '{tool_name}' denied (spike test)")

    # --- Build MCP server with a simple tool (for visibility) ---
    @sdk_tool("get_weather", "Get current weather for a city", {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    })
    async def get_weather(args: dict[str, Any]) -> dict[str, Any]:
        # This should NEVER be called if deny-all works
        logger.error("!!! MCP HANDLER CALLED — deny-all FAILED !!!")
        return {"content": [{"type": "text", "text": "72°F sunny"}]}

    mcp_server = create_sdk_mcp_server("spike-test", tools=[get_weather])

    # --- Test mode selection ---
    import sys
    test_mode = sys.argv[1] if len(sys.argv) > 1 else "deny-with-mcp"
    print(f"Test mode: {test_mode}")

    if test_mode == "deny-with-mcp":
        # Mode 1: MCP server registered + deny-all callback
        # DO NOT set permission_mode="bypassPermissions" — it overrides can_use_tool!
        options = ClaudeAgentOptions(
            cli_path=cli_path,
            model="haiku",
            cwd=".",
            can_use_tool=deny_all_tools,
            mcp_servers={"spike": mcp_server},
            max_turns=1,
            max_budget_usd=0.10,
            allowed_tools=[],
        )
    elif test_mode == "deny-no-mcp":
        # Mode 2: NO MCP server, tools described in system prompt
        options = ClaudeAgentOptions(
            cli_path=cli_path,
            model="haiku",
            cwd=".",
            can_use_tool=deny_all_tools,
            max_turns=1,
            max_budget_usd=0.10,
            allowed_tools=[],
            system_prompt=(
                "You have access to a tool called 'get_weather' that takes a 'city' parameter. "
                "When you want to use it, output a tool_use block."
            ),
        )
    elif test_mode == "deny-interrupt":
        # Mode 3: deny with interrupt=True
        async def deny_with_interrupt(
            tool_name: str,
            tool_input: dict[str, Any],
            context: ToolPermissionContext,
        ) -> PermissionResultDeny:
            nonlocal deny_count
            deny_count += 1
            logger.info(f"DENY+INTERRUPT #{deny_count}: tool={tool_name}")
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' denied",
                interrupt=True,
            )

        options = ClaudeAgentOptions(
            cli_path=cli_path,
            model="haiku",
            cwd=".",
            can_use_tool=deny_with_interrupt,
            mcp_servers={"spike": mcp_server},
            max_turns=1,
            max_budget_usd=0.10,
            allowed_tools=[],
        )
    else:
        print(f"Unknown mode: {test_mode}")
        return

    # --- Prompt that should trigger tool use ---
    prompt = "What is the weather in San Francisco? Use the get_weather tool."

    # Since we have mcp_servers, we need streaming prompt
    async def _stream_prompt():
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    # --- Collect all messages ---
    messages_received: list[tuple[str, Any]] = []
    tool_use_blocks_found: list[dict] = []
    tool_result_blocks_found: list[dict] = []

    print("\n=== Starting SDK query with max_turns=1 + deny-all ===\n")

    try:
        async for message in query(prompt=_stream_prompt(), options=options):
            msg_type = type(message).__name__
            messages_received.append((msg_type, message))
            logger.info(f"Received: {msg_type}")

            if isinstance(message, AssistantMessage):
                logger.info(f"  AssistantMessage has {len(message.content)} blocks:")
                for i, block in enumerate(message.content):
                    block_type = type(block).__name__
                    if block_type == "ToolUseBlock" or getattr(block, "type", None) == "tool_use":
                        tool_use_blocks_found.append({
                            "id": getattr(block, "id", ""),
                            "name": getattr(block, "name", ""),
                            "input": getattr(block, "input", {}),
                        })
                        logger.info(f"    [{i}] tool_use: name={getattr(block, 'name', '')}")
                    elif block_type == "TextBlock" or getattr(block, "type", None) == "text":
                        text = getattr(block, "text", "")
                        logger.info(f"    [{i}] text ({len(text)} chars): {text[:200]}")
                    else:
                        logger.info(f"    [{i}] {block_type}: {str(block)[:100]}")

            elif isinstance(message, UserMessage):
                if hasattr(message, "content"):
                    for block in message.content:
                        block_type = type(block).__name__
                        if block_type == "ToolResultBlock" or getattr(block, "type", None) == "tool_result":
                            tool_result_blocks_found.append({
                                "tool_use_id": getattr(block, "tool_use_id", ""),
                                "content": str(getattr(block, "content", ""))[:200],
                                "is_error": getattr(block, "is_error", False),
                            })
                            logger.info(f"  tool_result: is_error={getattr(block, 'is_error', False)}, content={str(getattr(block, 'content', ''))[:100]}")

            elif isinstance(message, ResultMessage):
                logger.info(f"  num_turns={getattr(message, 'num_turns', '?')}")
                logger.info(f"  is_error={getattr(message, 'is_error', False)}")
                usage = getattr(message, "usage", None)
                if usage:
                    logger.info(f"  usage={usage}")

    except Exception as e:
        logger.error(f"SDK error: {e}", exc_info=True)

    # --- Report ---
    print("\n=== RESULTS ===\n")
    print(f"Messages received: {len(messages_received)}")
    for msg_type, _ in messages_received:
        print(f"  - {msg_type}")

    print(f"\ntool_use blocks found: {len(tool_use_blocks_found)}")
    for tu in tool_use_blocks_found:
        print(f"  - {tu['name']}({tu['input']})")

    print(f"\ntool_result blocks found: {len(tool_result_blocks_found)}")
    for tr in tool_result_blocks_found:
        print(f"  - is_error={tr['is_error']}, content={tr['content'][:100]}")

    print(f"\nDeny callback invocations: {deny_count}")

    # --- Verdicts ---
    print("\n=== VERDICTS ===\n")

    if tool_use_blocks_found:
        print("PASS: SDK yielded AssistantMessage with tool_use blocks")
    else:
        print("FAIL: No tool_use blocks found — model may not have seen the tool")

    if deny_count > 0:
        print(f"PASS: can_use_tool callback was invoked ({deny_count} times)")
    else:
        print("WARN: can_use_tool callback was never invoked")

    # Check if MCP handler was called (it shouldn't be)
    # We can't directly check this from here, but the error log above would show it

    if tool_result_blocks_found:
        all_errors = all(tr["is_error"] for tr in tool_result_blocks_found)
        if all_errors:
            print("PASS: tool_result blocks are all errors (denied, not executed)")
        else:
            print("FAIL: Some tool_result blocks are NOT errors — tools may have been executed")
    else:
        print("INFO: No tool_result blocks — SDK may not emit them when denied")

    result_msgs = [m for t, m in messages_received if t == "ResultMessage"]
    if result_msgs:
        rm = result_msgs[0]
        num_turns = getattr(rm, "num_turns", None)
        print(f"INFO: ResultMessage.num_turns = {num_turns}")
        if num_turns == 1:
            print("PASS: SDK stopped after 1 turn as expected")
        else:
            print(f"WARN: SDK ran {num_turns} turns (expected 1)")
    else:
        print("WARN: No ResultMessage received")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
