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
                    "cleanup_status",
                    "cleanup_checkpoints",
                    "salvage_orphan",
                    "cleanup_all_safe",
                    "smart_sync",
                    "finalize_merge",
                    "resolve_conflict",
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
                "description": "Task ID (for get_context, dispatch, salvage_orphan, finalize_merge, resolve_conflict, reconcile, retire_lane, done, abandon, cancel)",
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
                "description": "Project ID for routing (e.g., summitflow, agent-hub); required for cleanup_status, cleanup_checkpoints, salvage_orphan, and smart_sync, not used by cleanup_all_safe, and recommended for finalize_merge",
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
            "objective": {
                "type": "string",
                "description": "Short statement of the task's concrete objective (for plan-based create)",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Scope boundaries, non-goals, or hard requirements to preserve during execution",
            },
            "spirit_anti": {
                "type": "string",
                "description": "Explicit anti-goal describing what the task must avoid or refuse to become",
            },
            "testing_strategy": {
                "type": "string",
                "description": "How the implementation should be verified beyond generic quality checks",
            },
            "context": {
                "type": "object",
                "description": "Optional rich plan context passed through to SummitFlow task_spirit context",
                "properties": {
                    "files_to_modify": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Existing files expected to change",
                    },
                    "files_to_create": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "New files expected to be created",
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Known risks, gotchas, or rollout concerns",
                    },
                    "references": {
                        "type": "array",
                        "description": "External references for the task",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"}
                            },
                            "required": ["title", "url"]
                        }
                    },
                    "second_opinion": {
                        "type": "object",
                        "description": "Optional critique-tracking metadata for task-shape or pre-close review",
                        "properties": {
                            "required": {"type": "boolean"},
                            "stage": {
                                "type": "string",
                                "enum": ["task_shape", "pre_close", "both"]
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "completed", "waived", "needs_revision"]
                            },
                            "summary": {"type": "string"}
                        },
                        "required": ["required", "stage", "status", "summary"]
                    }
                }
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
                        "phase": {
                            "type": "string",
                            "description": "Grouping label such as backend, frontend, or verification",
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
                        "steps": {
                            "type": "array",
                            "description": "Ordered implementation or verification steps for the subtask",
                            "items": {
                                "anyOf": [
                                    {"type": "string"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "description": {"type": "string"},
                                            "spec": {
                                                "type": "object",
                                                "description": "Free-form step metadata such as verify_command",
                                                "additionalProperties": True
                                            }
                                        },
                                        "required": ["description"]
                                    }
                                ]
                            }
                        }
                    },
                    "required": ["id", "description"],
                },
            },
        },
        "required": ["action"],
    },
    category="tasks",
    search_keywords=["tasks", "summitflow", "dispatch", "task context"],
    usage_examples=["Get full context for a task before dispatching follow-up work."],
)

MANAGE_BACKUPS_TOOL = Tool(
    name="manage_backups",
    description=(
        "Inspect protection state and run backup operations. Use this for routine backup "
        "checks, pre-risk snapshots, schedule review, and restore dry-runs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "protection_status",
                    "status",
                    "sources",
                    "list",
                    "create",
                    "restore",
                    "schedule",
                ],
                "description": "The backup operation to perform",
            },
            "project_id": {
                "type": "string",
                "description": "Project-scoped backup target (e.g. summitflow, agent-hub)",
            },
            "source_id": {
                "type": "string",
                "description": "Non-project backup source (e.g. .claude, persona-sandbox) or explicit source for schedule",
            },
            "backup_id": {
                "type": "string",
                "description": "Backup ID for restore",
            },
            "note": {
                "type": "string",
                "description": "Optional note for manual backups",
            },
            "keep_local": {
                "type": "boolean",
                "description": "Keep a local copy of a manual backup",
                "default": False,
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview a restore without applying it",
                "default": True,
            },
            "source_type": {
                "type": "string",
                "enum": ["project", "config", "workspace"],
                "description": "Optional source-type filter for sources/protection checks",
            },
            "status": {
                "type": "string",
                "description": "Optional backup status filter for list",
            },
            "limit": {
                "type": "integer",
                "description": "Max backups to show for list",
                "default": 10,
            },
            "enable": {
                "type": "boolean",
                "description": "Enable or disable a backup schedule",
            },
            "frequency": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly"],
                "description": "Schedule frequency to set",
            },
            "retention_days": {
                "type": "integer",
                "description": "Retention period for scheduled backups",
            },
        },
        "required": ["action"],
    },
    category="operations",
    search_keywords=["backup", "restore", "dr", "recovery", "schedule"],
    usage_examples=[
        "Check protection state before risky cleanup work.",
        "Create a manual backup before a destructive bulk operation.",
        "Dry-run a restore before attempting full disaster recovery.",
    ],
)

# --- Model configuration tool ---

MANAGE_MODEL_CONFIG_TOOL = Tool(
    name="manage_model_config",
    description=(
        "Manage agent configuration across models and memory routing. List models, "
        "inspect agent details, update model settings, patch memory config, fetch "
        "external benchmarks, and review agents. You have full autonomy on these "
        "changes — no approval gates."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_models",
                    "get_model_details",
                    "get_agent_details",
                    "update_agent_model",
                    "update_agent_memory",
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
                "description": "Agent slug (for get_agent_details, update_agent_model, update_agent_memory)",
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
            "memory_config_patch": {
                "type": "object",
                "description": (
                    "Partial memory_config fields to merge into the current agent memory config "
                    "(for update_agent_memory)."
                ),
            },
            "add_audience_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Audience tags to add to agent memory routing (for update_agent_memory)",
            },
            "remove_audience_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Audience tags to remove from agent memory routing (for update_agent_memory)",
            },
            "clear_audience_tags": {
                "type": "boolean",
                "description": "Remove all audience tags before any add/remove operations (for update_agent_memory)",
                "default": False,
            },
            "add_exclude_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude tags to add to agent memory routing (for update_agent_memory)",
            },
            "remove_exclude_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exclude tags to remove from agent memory routing (for update_agent_memory)",
            },
            "clear_exclude_tags": {
                "type": "boolean",
                "description": "Remove all exclude tags before any add/remove operations (for update_agent_memory)",
                "default": False,
            },
        },
        "required": ["action"],
    },
    category="model-ops",
    search_keywords=["models", "benchmarks", "agent config", "memory routing"],
    usage_examples=["Review agent memory routing before changing audience tags or reference settings."],
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
    category="observability",
    search_keywords=["performance log", "feedback", "observation"],
    usage_examples=["Log repeated model friction after a failed session."],
    defer_loading=True,
)

MANAGE_FEEDBACK_TOOL = Tool(
    name="manage_feedback",
    description=(
        "Review and manage feedback items: search/list items, inspect details, "
        "summarize hotspots, archive or resolve cleaned-up items, merge duplicates, "
        "delete junk, and vote on items you've also observed. Use [[F:...]] tags to "
        "file new feedback."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "search",
                    "list",
                    "get",
                    "summary",
                    "resolve",
                    "archive",
                    "vote",
                    "merge",
                    "delete",
                ],
                "description": "The feedback operation to perform",
            },
            "item_id": {
                "type": "string",
                "description": "Feedback item ID or prefix (for get, resolve, archive, vote, merge, delete)",
            },
            "target_item_id": {
                "type": "string",
                "description": "Canonical feedback item ID or prefix (for merge)",
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
                "enum": ["open", "acknowledged", "resolved", "wont_fix", "archived", "active"],
                "description": "Status filter (for list) or status to set (for resolve, default: resolved)",
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
                "description": "Filter by project (for search, list, summary)",
            },
            "sort": {
                "type": "string",
                "enum": ["votes", "newest", "oldest"],
                "description": "Sort order (for list, default: votes)",
                "default": "votes",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (for search, list, default: 20)",
                "default": 20,
            },
            "days": {
                "type": "integer",
                "description": "Lookback window in days (for summary, default: 30)",
                "default": 30,
            },
        },
        "required": ["action"],
    },
    category="observability",
    search_keywords=["feedback", "friction", "vote", "resolve", "summary", "cleanup"],
    usage_examples=["Search for existing feedback before filing a duplicate item."],
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
    category="observability",
    search_keywords=["sessions", "agent status", "dispatched agents"],
    usage_examples=["List recent completed coder sessions from the last two hours."],
)

INSPECT_SESSION_TOOL = Tool(
    name="inspect_session",
    description=(
        "Inspect one session by id and return its status, summary, recent tools, "
        "and latest assistant result. Use this to consume delegated-agent output."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Exact Agent Hub session id to inspect",
            },
        },
        "required": ["session_id"],
    },
    category="observability",
    search_keywords=["session details", "delegated result", "child session"],
    usage_examples=["Inspect a completed governance-auditor session before deciding the next action."],
)

SEARCH_PERSONA_HISTORY_TOOL = Tool(
    name="search_persona_history",
    description=(
        "Search persona heartbeat history and child-session outcomes using the same bounded "
        "search semantics as the persona workspace. Prefer this over rereading raw session "
        "logs when you need targeted self-reflection evidence."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query. Supports stream prefixes like task:, file:, agent:, "
                    "status:, project:, and topic:."
                ),
            },
            "hours_back": {
                "type": "integer",
                "description": "How many hours back to search (default: 168)",
                "default": 168,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum matches to return (default: 8)",
                "default": 8,
            },
            "project_id": {
                "type": "string",
                "description": "Optional project filter appended as project:<id> when missing",
            },
        },
        "required": ["query"],
    },
    category="observability",
    search_keywords=["persona history", "self reflection", "heartbeat recall", "search sessions"],
    usage_examples=["Search persona history for topic:task-123 before repeating the same blocker analysis."],
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
    category="observability",
    search_keywords=["performance review", "model history", "patterns"],
    usage_examples=["Review friction trends before changing an agent's primary model."],
    defer_loading=True,
)

REVIEW_IMPROVEMENT_SIGNALS_TOOL = Tool(
    name="review_improvement_signals",
    description=(
        "Review combined improvement signals from performance logs, benchmark experiments, "
        "regression clusters, and memory utilization. Use this before changing prompts, "
        "memory routing, or agent configs."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "Optional project filter (for project-scoped evidence)",
            },
            "primary_agent_slug": {
                "type": "string",
                "description": "Primary agent to focus benchmark/regression evidence on",
                "default": "persona",
            },
            "days_back": {
                "type": "integer",
                "description": "How many days back to analyze (default: 7)",
                "default": 7,
            },
            "include_team": {
                "type": "boolean",
                "description": "Include specialist/team performance signals alongside the primary agent",
                "default": True,
            },
            "max_agents": {
                "type": "integer",
                "description": "Max agents to summarize in the digest (default: 4)",
                "default": 4,
            },
            "max_references": {
                "type": "integer",
                "description": "Max low-yield references to show (default: 6)",
                "default": 6,
            },
        },
    },
    category="observability",
    search_keywords=["improvement", "benchmark", "memory yield", "regression clusters"],
    usage_examples=["Review combined evidence before retagging references or changing model config."],
    defer_loading=True,
)
