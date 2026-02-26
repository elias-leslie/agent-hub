"""Tool definitions for ideator agents (task creation and idea submission)."""

from __future__ import annotations

from app.services.tools.base import Tool

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


def get_ideator_tools() -> list[Tool]:
    """Get tool definitions for the ideator agent."""
    return [CREATE_TASK_TOOL]


def get_ideator_public_tools() -> list[Tool]:
    """Get tool definitions for the ideator-public agent."""
    return [SUBMIT_IDEA_TOOL]
