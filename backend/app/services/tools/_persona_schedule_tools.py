"""Persona tool definitions: scheduling and subagent steering."""

from __future__ import annotations

from app.services.tools.base import Tool

# --- Scheduling tools ---

SCHEDULE_JOB_TOOL = Tool(
    name="schedule_job",
    description=(
        "Create a scheduled job — set reminders, daily summaries, or recurring tasks. "
        "Supports one-shot (at), interval (every), and cron expressions. "
        "Can also schedule the persona's autonomous self-honing loop. "
        "Can also schedule rolling memory review."
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
                "description": (
                    "Message to inject as user input (agent_turn), push body (push), "
                    "or a human-readable note for self_honing jobs"
                ),
            },
            "payload_type": {
                "type": "string",
                "enum": ["agent_turn", "push", "self_honing", "memory_review"],
                "description": (
                    "agent_turn=run as agent, push=send notification, "
                    "self_honing=run the persona's scheduled self-honing loop, "
                    "memory_review=run one dedicated memory-curator review batch"
                ),
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
    category="persona-ops",
    search_keywords=["reminder", "cron", "schedule", "follow-up"],
    usage_examples=["Schedule a one-shot reminder for Monday at 09:00."],
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
    category="persona-ops",
    search_keywords=["jobs", "scheduled tasks", "timers"],
    usage_examples=["List active scheduled jobs before creating a duplicate."],
    defer_loading=True,
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
    category="persona-ops",
    search_keywords=["disable job", "remove reminder"],
    usage_examples=["Cancel a scheduled reminder after the issue is resolved."],
    defer_loading=True,
)

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
                "description": "The agent to dispatch (e.g., 'site-checker', 'coder', 'debugger')",
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
