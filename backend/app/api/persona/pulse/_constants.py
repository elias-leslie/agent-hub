"""Pulse classification constants — term lists and priority orderings."""

from __future__ import annotations

FILTERABLE_TAGS = (
    "friction",
    "error",
    "warning",
    "stalled",
    "retries",
    "instruction_drift",
    "tool_friction",
    "recovered",
    "escalation",
)
ROOT_CAUSE_PRIORITY = ("workflow", "tool", "context", "infra", "prompt", "unknown")
TAG_PRIORITY = (
    "instruction_drift",
    "error",
    "stalled",
    "tool_friction",
    "warning",
    "retries",
    "escalation",
    "recovered",
)
SUCCESS_TERMS = ("passed", "completed", "succeeded", "verified", "published", "merged", "fixed", "resolved")
ERROR_TERMS = (
    "error",
    "failed",
    "failure",
    "traceback",
    "exception",
    "enoent",
    "non-zero exit",
    "exit code 1",
    "exit code 2",
    "command failed",
)
WARNING_TERMS = ("warning", "blocked", "interrupted", "manual prerequisite", "manual prerequisites", "needs revision")
STALLED_TERMS = ("waiting", "stalled", "stuck", "hung", "awaiting", "blocked on", "pending approval", "manual prerequisite")
CONTEXT_TERMS = ("missing context", "need context", "insufficient context", "unclear context", "no task context", "lacked context")
INFRA_TERMS = (
    "redis",
    "postgres",
    "socket",
    "connection refused",
    "service unavailable",
    "network",
    "gateway timeout",
    "daemon",
)
PROMPT_TERMS = ("instruction", "instructions", "prompt", "mandate", "guardrail", "ignored")
ESCALATION_TERMS = ("escalate", "human", "manual intervention", "needs review", "approval", "user intervention")
TOOL_FRICTION_TERMS = (
    "not found",
    "missing",
    "invalid",
    "blank dom",
    "fetch failed",
    "timed out",
    "timeout",
    "unsupported",
)
RAW_COMMAND_RULES: tuple[tuple[str, str, str], ...] = (
    ("pytest", "workflow", "Used raw pytest instead of dt"),
    ("ruff", "workflow", "Used raw ruff instead of dt"),
    ("mypy", "workflow", "Used raw mypy instead of dt"),
    ("tsc", "workflow", "Used raw tsc instead of dt"),
    ("biome", "workflow", "Used raw biome instead of dt"),
    ("git commit", "workflow", "Used raw git commit instead of commit.sh"),
    ("systemctl", "workflow", "Used systemctl instead of restart.sh/rebuild.sh"),
    ("psql", "workflow", "Used raw psql instead of db"),
)
ALLOWED_COMMAND_PREFIXES = (
    "dt ",
    "st ",
    "db ",
    "bash ~/agent-hub/scripts/rebuild.sh",
    "bash ~/agent-hub/scripts/restart.sh",
    "commit.sh ",
)
HUMAN_TEXT_KEYS = ("summary", "content", "message", "stderr", "stdout", "error", "detail", "result")
