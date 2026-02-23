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


# Push notification tool for agents that need to reach the human
SEND_PUSH_TOOL = Tool(
    name="send_push",
    description=(
        "Send a push notification to the human's devices. Use this to proactively "
        "reach out when something needs attention — task failures, quality issues, "
        "blocked work, or anything that warrants interrupting their flow. "
        "Be thoughtful: only push when it matters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short notification title (e.g., 'Build failing on main')",
            },
            "body": {
                "type": "string",
                "description": "Notification body — what happened, what it means, what you recommend",
            },
            "url": {
                "type": "string",
                "description": "Optional deep-link URL to open when tapped",
            },
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "error", "critical"],
                "description": "Notification severity (default: info)",
                "default": "info",
            },
            "tag": {
                "type": "string",
                "description": "Optional dedup tag — same tag replaces previous notification",
            },
        },
        "required": ["title", "body"],
    },
)


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


# Personality self-modification tools for the persona agent
READ_PERSONALITY_TOOL = Tool(
    name="read_personality",
    description=(
        "Read your current personality document. This defines your personality, "
        "principles, and operating style. Use this to review before making changes."
    ),
    input_schema={
        "type": "object",
        "properties": {},
    },
)

WRITE_PERSONALITY_TOOL = Tool(
    name="write_personality",
    description=(
        "Update your personality document. Your personality evolves as you learn "
        "what works best. Only update when you've learned something fundamental "
        "about how you operate. Always tell the human when you update it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "personality": {
                "type": "string",
                "description": "The new personality document (markdown)",
            },
            "reason": {
                "type": "string",
                "description": "Why you're updating your personality — what you learned",
            },
        },
        "required": ["personality", "reason"],
    },
)


# Journal tools for persona temporal continuity
WRITE_JOURNAL_TOOL = Tool(
    name="write_journal",
    description=(
        "Write a journal entry for today. Use this to record observations, decisions, "
        "learnings, and user insights. Journal entries provide temporal continuity — "
        "recent entries are automatically included in your context."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The journal entry content (markdown)",
            },
            "entry_type": {
                "type": "string",
                "enum": ["observation", "decision", "learning", "user_insight"],
                "description": "Type of journal entry (default: observation)",
                "default": "observation",
            },
        },
        "required": ["content"],
    },
)

READ_JOURNAL_TOOL = Tool(
    name="read_journal",
    description=(
        "Read your recent journal entries. Returns entries from the last N days "
        "to review your observations, decisions, and learnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "days_back": {
                "type": "integer",
                "description": "How many days of journal entries to retrieve (default: 7)",
                "default": 7,
            },
        },
    },
)

SEARCH_JOURNAL_TOOL = Tool(
    name="search_journal",
    description=(
        "Search your journal entries by content. Use when looking for specific "
        "past observations, decisions, or learnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text to find in journal entries",
            },
            "days_back": {
                "type": "integer",
                "description": "How many days back to search (default: 30)",
                "default": 30,
            },
        },
        "required": ["query"],
    },
)


# User context tools for persona
WRITE_USER_CONTEXT_TOOL = Tool(
    name="write_user_context",
    description=(
        "Update your knowledge about the user. Record preferences, patterns, "
        "communication style, and other user-specific information you learn. "
        "This is cumulative — update with the full document each time."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "user_context": {
                "type": "string",
                "description": "The updated user context document (markdown)",
            },
        },
        "required": ["user_context"],
    },
)

READ_USER_CONTEXT_TOOL = Tool(
    name="read_user_context",
    description="Read your current knowledge about the user.",
    input_schema={
        "type": "object",
        "properties": {},
    },
)


# Memory curation tools for persona long-term memory
MARK_MEMORY_RELEVANT_TOOL = Tool(
    name="mark_memory_relevant",
    description=(
        "Mark a memory episode as relevant to you. Adds the 'persona-relevant' tag "
        "so the memory is included in your long-term context. Use when you encounter "
        "a memory that contains important operational patterns, user preferences, or "
        "system knowledge you should retain."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_uuid": {
                "type": "string",
                "description": "UUID of the memory episode to mark as relevant",
            },
        },
        "required": ["memory_uuid"],
    },
)

MARK_MEMORY_IRRELEVANT_TOOL = Tool(
    name="mark_memory_irrelevant",
    description=(
        "Remove the 'persona-relevant' tag from a memory episode. Use when a "
        "previously marked memory is no longer relevant to your operation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "memory_uuid": {
                "type": "string",
                "description": "UUID of the memory episode to unmark",
            },
        },
        "required": ["memory_uuid"],
    },
)


# Onboarding submission tool for persona
SUBMIT_ONBOARDING_TOOL = Tool(
    name="submit_onboarding",
    description=(
        "Submit the completed onboarding profile for approval. Call this after "
        "all 10 onboarding topics have been covered and the user confirms they're "
        "satisfied. The profile will be reviewed by two independent models — both "
        "must approve before onboarding is considered complete. If rejected, you'll "
        "receive feedback on what to follow up on."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "A comprehensive summary of everything learned during onboarding, "
                    "organized by the 10 topic areas"
                ),
            },
        },
        "required": ["summary"],
    },
)


# --- Scheduling tools for persona ---

SCHEDULE_JOB_TOOL = Tool(
    name="schedule_job",
    description=(
        "Create a scheduled job — set reminders, daily summaries, or recurring tasks. "
        "Supports one-shot (at), interval (every), and cron expressions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable job name (e.g., 'Daily standup summary')",
            },
            "schedule_type": {
                "type": "string",
                "enum": ["at", "every", "cron"],
                "description": "at=one-shot ISO datetime, every=interval in ms, cron=cron expression",
            },
            "schedule_value": {
                "type": "string",
                "description": "ISO datetime (at), interval ms (every), or cron expr (cron)",
            },
            "payload_message": {
                "type": "string",
                "description": "Message to inject as user input (agent_turn) or push body",
            },
            "payload_type": {
                "type": "string",
                "enum": ["agent_turn", "push"],
                "description": "agent_turn=run as agent, push=send notification (default: agent_turn)",
                "default": "agent_turn",
            },
            "delivery": {
                "type": "string",
                "enum": ["none", "push"],
                "description": "Whether to push-notify the result (default: none)",
                "default": "none",
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone for cron scheduling (default: UTC)",
                "default": "UTC",
            },
        },
        "required": ["name", "schedule_type", "schedule_value", "payload_message"],
    },
)

LIST_SCHEDULED_JOBS_TOOL = Tool(
    name="list_scheduled_jobs",
    description="List scheduled jobs. Shows name, schedule, next run, and run count.",
    input_schema={
        "type": "object",
        "properties": {
            "include_disabled": {
                "type": "boolean",
                "description": "Include disabled/completed jobs (default: false)",
                "default": False,
            },
        },
    },
)

CANCEL_SCHEDULED_JOB_TOOL = Tool(
    name="cancel_scheduled_job",
    description="Disable or permanently delete a scheduled job.",
    input_schema={
        "type": "object",
        "properties": {
            "job_id": {
                "type": "string",
                "description": "UUID of the job to cancel",
            },
            "hard_delete": {
                "type": "boolean",
                "description": "Permanently delete instead of just disabling (default: false)",
                "default": False,
            },
        },
        "required": ["job_id"],
    },
)


# --- Subagent steering tools for persona ---

STEER_CONSULTATION_TOOL = Tool(
    name="steer_consultation",
    description=(
        "Send a follow-up message to an existing consultation session. "
        "Use the session_id from a previous consult_agent response."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session ID from a previous consult_agent response",
            },
            "message": {
                "type": "string",
                "description": "Follow-up message to send to the consultation",
            },
        },
        "required": ["session_id", "message"],
    },
)

LIST_CONSULTATIONS_TOOL = Tool(
    name="list_consultations",
    description="List recent consultation sessions with other agents.",
    input_schema={
        "type": "object",
        "properties": {
            "hours_back": {
                "type": "integer",
                "description": "How many hours back to look (default: 24)",
                "default": 24,
            },
            "agent_slug": {
                "type": "string",
                "description": "Filter by consulted agent slug (optional)",
            },
        },
    },
)

CANCEL_CONSULTATION_TOOL = Tool(
    name="cancel_consultation",
    description="Close a running consultation session.",
    input_schema={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session ID of the consultation to close",
            },
        },
        "required": ["session_id"],
    },
)


# --- Task orchestration tool for persona ---

MANAGE_TASKS_TOOL = Tool(
    name="manage_tasks",
    description=(
        "Quick task operations via SummitFlow. For complex operations, use bash + st CLI."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list_ready", "get_context", "create", "dispatch"],
                "description": "The task operation to perform",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (for get_context, dispatch)",
            },
            "title": {
                "type": "string",
                "description": "Task title (for create)",
            },
            "description": {
                "type": "string",
                "description": "Task description (for create)",
            },
            "priority": {
                "type": "integer",
                "description": "Priority 0-4 (for create, default: 2)",
                "default": 2,
            },
            "task_type": {
                "type": "string",
                "description": "Task type (for create, default: task)",
                "default": "task",
            },
            "labels": {
                "type": "string",
                "description": "Comma-separated labels (for create)",
            },
        },
        "required": ["action"],
    },
)


# Agent slug → tool definitions mapping
_AGENT_TOOL_REGISTRY: dict[str, list[Tool]] = {
    "ideator": [CREATE_TASK_TOOL],
    "ideator-public": [SUBMIT_IDEA_TOOL],
    "persona": [
        *STANDARD_TOOLS,
        SEND_PUSH_TOOL,
        READ_PERSONALITY_TOOL,
        WRITE_PERSONALITY_TOOL,
        WRITE_JOURNAL_TOOL,
        READ_JOURNAL_TOOL,
        SEARCH_JOURNAL_TOOL,
        WRITE_USER_CONTEXT_TOOL,
        READ_USER_CONTEXT_TOOL,
        MARK_MEMORY_RELEVANT_TOOL,
        MARK_MEMORY_IRRELEVANT_TOOL,
        SUBMIT_ONBOARDING_TOOL,
        # Scheduling
        SCHEDULE_JOB_TOOL,
        LIST_SCHEDULED_JOBS_TOOL,
        CANCEL_SCHEDULED_JOB_TOOL,
        # Subagent steering
        STEER_CONSULTATION_TOOL,
        LIST_CONSULTATIONS_TOOL,
        CANCEL_CONSULTATION_TOOL,
        # Task orchestration
        MANAGE_TASKS_TOOL,
    ],
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
