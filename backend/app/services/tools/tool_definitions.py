"""Standard tool definitions for agent tool execution.

Defines the schema and metadata for bash, read_file, write_file, and
consult_agent tools.
"""

from __future__ import annotations

from typing import Any

from app.services.tools.base import Tool

# Default timeout for commands
DEFAULT_TIMEOUT = 120

# Standard tool definitions for agents
STANDARD_TOOLS = [
    Tool(
        name="bash",
        description="Execute a bash command in the working directory. Use for running tests, git operations, or system commands.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                    "default": DEFAULT_TIMEOUT,
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
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
                    "default": 2000,
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed.",
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
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="consult_agent",
        description=(
            "Consult another agent for advice or help. Use when stuck on a problem, "
            "need expert review, or want a second opinion. The consulted agent will "
            "analyze your question and provide guidance but will not execute any tools. "
            "Available agents: 'supervisor' (coordination/strategy), 'reviewer' (code review)."
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
    ),
]


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()


# Task ideation tool for the ideator agent (interactive mode)
CREATE_TASK_TOOL = Tool(
    name="create_task",
    description=(
        "Create a fully-scoped task from the ideation conversation. "
        "Call this when you have enough clarity on what needs to be built."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Concise, actionable task title in imperative form",
            },
            "description": {
                "type": "string",
                "description": "Rich description with context, scope, and what success looks like",
            },
            "priority": {
                "type": "string",
                "enum": ["P0", "P1", "P2", "P3", "P4"],
            },
            "task_type": {
                "type": "string",
                "enum": ["feature", "bug", "task", "refactor", "debt", "regression"],
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
            },
            "complexity": {
                "type": "string",
                "enum": ["simple", "standard", "complex"],
            },
        },
        "required": ["title", "description", "priority", "task_type", "complexity"],
    },
)


def get_ideator_tools() -> list[Tool]:
    """Get tool definitions for the ideator agent."""
    return [CREATE_TASK_TOOL]


# Idea submission tool for the ideator-public agent
SUBMIT_IDEA_TOOL = Tool(
    name="submit_idea",
    description=(
        "Submit a game idea from the player. "
        "Call this when you understand what they want."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, catchy title for the idea",
            },
            "description": {
                "type": "string",
                "description": (
                    "Clear description of the idea with enough detail "
                    "to understand what the player wants"
                ),
            },
            "category": {
                "type": "string",
                "enum": ["gameplay", "characters", "visuals", "audio", "other"],
                "description": "Which area of the game this idea relates to",
            },
        },
        "required": ["title", "description"],
    },
)


def get_ideator_public_tools() -> list[Tool]:
    """Get tool definitions for the ideator-public agent."""
    return [SUBMIT_IDEA_TOOL]


# Agent slug → tool definitions mapping
_AGENT_TOOL_REGISTRY: dict[str, list[Tool]] = {
    "ideator": [CREATE_TASK_TOOL],
    "ideator-public": [SUBMIT_IDEA_TOOL],
}


def get_agent_tools(agent_slug: str) -> list[dict[str, Any]] | None:
    """Get tool definitions for an agent by slug.

    Returns tools as dicts (ready for adapter consumption), or None if
    the agent has no registered tools.
    """
    tools = _AGENT_TOOL_REGISTRY.get(agent_slug)
    if not tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]
