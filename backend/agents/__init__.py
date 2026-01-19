"""Agent module with registry and base classes.

This module provides the agent framework for Agent Hub:
- BaseAgent: Abstract base class for all agents
- AgentType: Enum of available agent types
- get_agent(): Factory function to get agent by type
- load_prompt(): Utility to load prompts from prompts/ directory
"""

from agents.base import BaseAgent
from agents.registry import (
    AgentType,
    get_agent,
    get_prompt,
    get_safety_directive,
    inject_safety_directive,
)

__all__ = [
    "BaseAgent",
    "AgentType",
    "get_agent",
    "get_prompt",
    "get_safety_directive",
    "inject_safety_directive",
]
