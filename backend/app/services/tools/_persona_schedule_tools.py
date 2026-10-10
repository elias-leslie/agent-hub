"""Persona tool definitions: subagent dispatch and consultation steering."""

from __future__ import annotations

from app.services.tools.base import Tool

# --- Subagent dispatch tools ---

DISPATCH_AGENT_TOOL = Tool(
    name="dispatch_agent",
    description=(
        "Dispatch an agent with full tool access to perform a task autonomously. "
        "Unlike consult_agent (bounded read-only advice and research), the dispatched agent "
        "can use bash, read_file, write_file, agent-browser, and other tools. Returns the "
        "agent's final response summarizing what it did. "
        "Your agent roster shows available agents."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "The agent to dispatch (e.g., 'coder', 'debugger', 'reviewer')",
            },
            "task": {
                "type": "string",
                "description": "Detailed task description for the agent to execute",
            },
            "project_id": {
                "type": "string",
                "description": "Project context for the dispatch (e.g., 'agent-hub', 'summitflow')",
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum agentic turns. Omit to use the persona's configured limit.",
            },
        },
        "required": ["agent_slug", "task", "project_id"],
    },
    category="agents",
    search_keywords=["delegate", "autonomous agent", "dispatch work"],
    usage_examples=["Dispatch the debugger agent to repair a failing test lane."],
)

# --- Subagent steering tools ---

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
    category="agents",
    search_keywords=["follow-up", "continue consultation"],
    usage_examples=["Ask a consulted agent to clarify an earlier recommendation."],
    defer_loading=True,
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
    category="agents",
    search_keywords=["consultations", "agent sessions"],
    usage_examples=["Review recent consultations before opening a new one."],
    defer_loading=True,
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
    category="agents",
    search_keywords=["close consultation", "stop session"],
    usage_examples=["Cancel a stale consultation once the main task is resolved."],
    defer_loading=True,
)
