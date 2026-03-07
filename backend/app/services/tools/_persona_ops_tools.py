"""Persona tool definitions: task orchestration, model config, and agent performance."""

from __future__ import annotations

from app.constants import SUBTASK_TYPES
from app.services.tools.base import Tool

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
                "enum": [
                    "overview",
                    "get_context",
                    "create",
                    "dispatch",
                    "reconcile",
                    "retire_lane",
                    "done",
                    "abandon",
                    "cancel",
                ],
                "description": "The task operation to perform",
            },
            "task_id": {
                "type": "string",
                "description": "Task ID (for get_context, dispatch, reconcile, retire_lane, done, abandon, cancel)",
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
            "project_id": {
                "type": "string",
                "description": "Project ID for routing (e.g., summitflow, agent-hub)",
            },
            "objective": {
                "type": "string",
                "description": "Task objective / spirit.why (for create with intent)",
            },
            "spirit_anti": {
                "type": "string",
                "description": "What NOT to do (for create with intent)",
            },
            "done_when": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Completion criteria checklist (for create with intent)",
            },
            "complexity": {
                "type": "string",
                "enum": ["SIMPLE", "STANDARD", "COMPLEX"],
                "description": "Task complexity level (for create with intent)",
            },
            "subtasks": {
                "type": "array",
                "description": "Typed subtasks for plan-based creation. Each gets routed to the right specialist agent.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Subtask ID like 1.1, 2.1",
                        },
                        "description": {
                            "type": "string",
                            "description": "What this subtask accomplishes",
                        },
                        "subtask_type": {
                            "type": "string",
                            "enum": list(SUBTASK_TYPES),
                            "description": "Agent routing type — determines specialist agent",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Subtask IDs that must complete first",
                        },
                    },
                    "required": ["id", "description"],
                },
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
            "format": {
                "type": "string",
                "enum": ["detailed", "compact"],
                "description": "Output format for list_agents: detailed (full config) or compact (one-liner per agent, active only)",
                "default": "detailed",
            },
            "coding_only": {
                "type": "boolean",
                "description": "Optional filter for list_agents. true=coding agents only, false=non-coding only.",
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

MANAGE_FEEDBACK_TOOL = Tool(
    name="manage_feedback",
    description=(
        "Triage feedback items: search open items, resolve fixed ones, "
        "or vote on items you've also observed. Use [[F:...]] tags to file new feedback."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "resolve", "vote"],
                "description": "The feedback operation to perform",
            },
            "item_id": {
                "type": "string",
                "description": "Feedback item ID or prefix (for resolve, vote)",
            },
            "query": {
                "type": "string",
                "description": "Full-text search query (for search)",
            },
            "component_id": {
                "type": "string",
                "description": "Filter by component (for search, e.g. sf.cli, ah.memory)",
            },
            "feedback_type": {
                "type": "string",
                "enum": ["friction", "improvement", "idea", "praise"],
                "description": "Filter by feedback type (for search)",
            },
            "status": {
                "type": "string",
                "enum": ["resolved", "wont_fix", "acknowledged"],
                "description": "Status to set (for resolve, default: resolved)",
            },
            "resolution_note": {
                "type": "string",
                "description": "Note explaining resolution (for resolve)",
            },
            "comment": {
                "type": "string",
                "description": "Comment to attach to vote (for vote)",
            },
            "project_id": {
                "type": "string",
                "description": "Filter by project (for search)",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (for search, default: 20)",
                "default": 20,
            },
        },
        "required": ["action"],
    },
)

QUERY_SESSIONS_TOOL = Tool(
    name="query_sessions",
    description=(
        "Query agent sessions to check progress, find stuck agents, or review "
        "what dispatched agents accomplished. Filters by agent, status, and time window."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "agent_slug": {
                "type": "string",
                "description": "Filter by agent slug (e.g., coder, explorer)",
            },
            "status": {
                "type": "string",
                "enum": ["active", "completed", "failed"],
                "description": "Filter by session status",
            },
            "hours_back": {
                "type": "integer",
                "description": "How many hours back to look (default: 24)",
                "default": 24,
            },
            "limit": {
                "type": "integer",
                "description": "Max sessions to return (default: 10)",
                "default": 10,
            },
            "parent_session_id": {
                "type": "string",
                "description": "Filter to sessions dispatched from a specific parent session",
            },
        },
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
