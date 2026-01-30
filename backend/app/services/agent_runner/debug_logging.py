"""Debug logging utilities for agent execution tracing."""

import json
import logging
from typing import Any

# Dedicated debug logger for agent execution tracing
debug_logger = logging.getLogger("agent_runner.debug")


def log_agent_input(
    agent_id: str, system_prompt: str | None, task: str, model: str, provider: str
) -> None:
    """Log the full input sent to the agent for debugging."""
    debug_logger.info(
        "\n" + "=" * 80 + "\n"
        f"AGENT INPUT [{agent_id}]\n"
        f"Provider: {provider} | Model: {model}\n" + "-" * 80 + "\n"
        f"SYSTEM PROMPT:\n{system_prompt or '(none)'}\n" + "-" * 80 + "\n"
        f"TASK:\n{task}\n" + "=" * 80
    )


def log_tool_call(agent_id: str, turn: int, tool_name: str, tool_input: dict[str, Any]) -> None:
    """Log a tool call for debugging."""
    debug_logger.info(
        f"\n[{agent_id}] Turn {turn} - TOOL CALL: {tool_name}\n"
        f"Arguments: {json.dumps(tool_input, indent=2, default=str)}"
    )


def log_tool_result(agent_id: str, turn: int, tool_name: str, result: str) -> None:
    """Log a tool result for debugging."""
    truncated = result[:500] + "..." if len(result) > 500 else result
    debug_logger.info(f"\n[{agent_id}] Turn {turn} - TOOL RESULT: {tool_name}\nOutput: {truncated}")


def log_agent_response(agent_id: str, turn: int, content: str, finish_reason: str) -> None:
    """Log the agent's response for debugging."""
    truncated = content[:1000] + "..." if len(content) > 1000 else content
    debug_logger.info(
        f"\n[{agent_id}] Turn {turn} - RESPONSE (finish_reason={finish_reason}):\n{truncated}"
    )


def log_final_output(
    agent_id: str, status: str, content: str, turns: int, tool_calls_count: int
) -> None:
    """Log the final agent output for debugging."""
    debug_logger.info(
        "\n" + "=" * 80 + "\n"
        f"AGENT OUTPUT [{agent_id}]\n"
        f"Status: {status} | Turns: {turns} | Tool Calls: {tool_calls_count}\n" + "-" * 80 + "\n"
        f"FINAL CONTENT:\n{content}\n" + "=" * 80
    )
