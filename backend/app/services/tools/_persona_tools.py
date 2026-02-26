"""Tool definitions for the persona agent (personality, journal, memory, scheduling, etc.)."""

from __future__ import annotations

from app.services.tools.base import Tool

# --- Personality self-modification tools ---

READ_PERSONALITY_TOOL = Tool(
    name="read_personality",
    description=(
        "Read your current personality document. This defines your personality, "
        "principles, and operating style. Use this to review before making changes."
    ),
    input_schema={"type": "object", "properties": {}},
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

# --- Journal tools ---

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

# --- User context tools ---

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
    input_schema={"type": "object", "properties": {}},
)

# --- Memory curation tools ---

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

# --- Onboarding tool ---

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

# --- Scheduling tools ---

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

# --- Task orchestration tool ---

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

# --- Model configuration tool ---

MANAGE_MODEL_CONFIG_TOOL = Tool(
    name="manage_model_config",
    description=(
        "Manage model configurations across agents. List models, view details, "
        "update agent model settings, fetch external benchmarks, and review agents. "
        "You have full autonomy on model decisions — no approval gates."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_models",
                    "get_model_details",
                    "update_agent_model",
                    "get_benchmarks",
                    "list_agents",
                ],
                "description": "The operation to perform",
            },
            "model_id": {
                "type": "string",
                "description": "Model ID (for get_model_details)",
            },
            "agent_slug": {
                "type": "string",
                "description": "Agent slug (for update_agent_model)",
            },
            "primary_model_id": {
                "type": "string",
                "description": "New primary model ID (for update_agent_model)",
            },
            "fallback_models": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New fallback model list (for update_agent_model)",
            },
            "escalation_model_id": {
                "type": "string",
                "description": "New escalation model ID (for update_agent_model)",
            },
            "temperature": {
                "type": "number",
                "description": "New temperature setting (for update_agent_model)",
            },
            "thinking_level": {
                "type": "string",
                "enum": ["minimal", "low", "medium", "high"],
                "description": "New thinking level (for update_agent_model)",
            },
            "change_reason": {
                "type": "string",
                "description": "Why this model change is being made (for audit trail)",
            },
        },
        "required": ["action"],
    },
)

# --- Agent performance logging tools ---

LOG_AGENT_PERFORMANCE_TOOL = Tool(
    name="log_agent_performance",
    description=(
        "Log a performance observation for an agent/model combination. Track friction, "
        "improvements, ideas, and praise to build a data-driven understanding of how "
        "agents and models perform across different task types."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "The agent being observed",
            },
            "model_id": {
                "type": "string",
                "description": "The model used for this observation",
            },
            "feedback_type": {
                "type": "string",
                "enum": ["friction", "improvement", "idea", "praise"],
                "description": "Type of feedback",
            },
            "content": {
                "type": "string",
                "description": "Your observation — what happened, what you noticed, why it matters",
            },
            "outcome": {
                "type": "string",
                "enum": ["success", "partial", "failure", "timeout", "fallback"],
                "description": "Outcome of the interaction (default: success)",
                "default": "success",
            },
            "task_type": {
                "type": "string",
                "description": "Type of task (e.g., coding, review, planning, heartbeat)",
            },
            "project_id": {
                "type": "string",
                "description": "Project context",
            },
            "session_id": {
                "type": "string",
                "description": "Session ID for traceability",
            },
            "duration_ms": {
                "type": "integer",
                "description": "Execution duration in milliseconds",
            },
            "input_tokens": {
                "type": "integer",
                "description": "Input tokens used",
            },
            "output_tokens": {
                "type": "integer",
                "description": "Output tokens generated",
            },
            "tool_calls_count": {
                "type": "integer",
                "description": "Number of tool calls made",
            },
            "turns": {
                "type": "integer",
                "description": "Number of agentic turns",
            },
        },
        "required": ["agent_slug", "model_id", "feedback_type", "content"],
    },
)

REVIEW_AGENT_PERFORMANCE_TOOL = Tool(
    name="review_agent_performance",
    description=(
        "Review performance history for agents and models. Aggregate observations, "
        "identify patterns, and inform model selection decisions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "Filter by agent slug",
            },
            "model_id": {
                "type": "string",
                "description": "Filter by model ID",
            },
            "feedback_type": {
                "type": "string",
                "enum": ["friction", "improvement", "idea", "praise"],
                "description": "Filter by feedback type",
            },
            "days_back": {
                "type": "integer",
                "description": "How many days back to look (default: 30)",
                "default": 30,
            },
            "limit": {
                "type": "integer",
                "description": "Max entries to return (default: 50)",
                "default": 50,
            },
        },
    },
)

# Consolidated list of all persona-specific tools (excluding standard tools)
PERSONA_EXTRA_TOOLS: list[Tool] = [
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
    SCHEDULE_JOB_TOOL,
    LIST_SCHEDULED_JOBS_TOOL,
    CANCEL_SCHEDULED_JOB_TOOL,
    STEER_CONSULTATION_TOOL,
    LIST_CONSULTATIONS_TOOL,
    CANCEL_CONSULTATION_TOOL,
    MANAGE_TASKS_TOOL,
    MANAGE_MODEL_CONFIG_TOOL,
    LOG_AGENT_PERFORMANCE_TOOL,
    REVIEW_AGENT_PERFORMANCE_TOOL,
]
