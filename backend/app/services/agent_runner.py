"""Agent Runner service for autonomous task execution.

Provides agentic completion with tool execution loops:
- For Claude: Uses enable_programmatic_tools (code_execution sandbox)
- For Gemini: Executes provided tool handlers in a loop

The agent runner handles the turn-based conversation loop, executing
tool calls and feeding results back until the task is complete.

This module now imports from the agent_runner package for better organization.
"""

# Import all public APIs from the new package structure
from app.services.agent_runner.models import (
    MAX_AGENT_TURNS,
    AgentConfig,
    AgentProgress,
    AgentResult,
)
from app.services.agent_runner.runner import AgentRunner, get_agent_runner

__all__ = [
    "MAX_AGENT_TURNS",
    "AgentConfig",
    "AgentProgress",
    "AgentResult",
    "AgentRunner",
    "get_agent_runner",
]
