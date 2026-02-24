"""Tool handler implementation for direct tool execution.

Provides DirectToolHandler which routes tool calls to DirectToolExecutor
methods and handles permission checking, including project-level
permission tier enforcement.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.tools.base import (
    PreToolUseHook,
    ToolCall,
    ToolDecision,
    ToolHandler,
    ToolResult,
)
from app.services.tools.direct_executor_core import DirectToolExecutor
from app.services.tools.tool_definitions import DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

# Claude Agent SDK uses PascalCase tool names (Bash, Read, Write, Edit)
# but our handler uses lowercase names. Normalize before routing.
_SDK_TOOL_NAME_MAP: dict[str, str] = {
    "Bash": "bash",
    "Read": "read_file",
    "Write": "write_file",
    "Edit": "write_file",
}

# Tools that require audit logging due to security sensitivity.
# Maps tool name → sensitivity level for filtering/alerting.
SENSITIVE_TOOLS: dict[str, str] = {
    "bash": "high",      # Arbitrary command execution
    "write_file": "high",  # File system modification
    "send_push": "medium",  # External communication
}


class DirectToolHandler(ToolHandler):
    """Tool handler that uses direct executor."""

    def __init__(
        self,
        working_dir: str | None = None,
        pre_hook: PreToolUseHook | None = None,
        project_id: str | None = None,
    ):
        """Initialize with working directory and optional permission hook.

        Args:
            working_dir: Base directory for all operations
            pre_hook: Optional async callback for permission checking
            project_id: Project ID for agent consultation (enables consult_agent)
        """
        super().__init__(pre_hook=pre_hook)
        self._executor = DirectToolExecutor(working_dir, project_id=project_id)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call with permission checking."""
        start = time.monotonic()
        # Normalize SDK PascalCase names to our lowercase convention
        tool_name = _SDK_TOOL_NAME_MAP.get(tool_call.name, tool_call.name)

        # Check permission before execution (project tier + config hooks)
        # Fail-closed: any exception during permission checking denies access.
        normalized_call = ToolCall(
            id=tool_call.id, name=tool_name, input=tool_call.input,
            caller=tool_call.caller, original_id=tool_call.original_id,
        )
        try:
            decision = await self.check_permission(normalized_call)
        except Exception as e:
            logger.error("Permission check error for tool '%s': %s — denying", tool_name, e)
            decision = ToolDecision.DENY
        if decision == ToolDecision.DENY:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Error: Tool '{tool_name}' denied by permission policy",
                is_error=True,
                duration_ms=duration_ms,
            )

        try:
            if tool_name == "bash":
                output = await self._executor.bash(
                    command=tool_call.input.get("command", ""),
                    timeout=tool_call.input.get("timeout", DEFAULT_TIMEOUT),
                )
            elif tool_name == "read_file":
                output = await self._executor.read_file(
                    path=tool_call.input.get("path", ""),
                    offset=tool_call.input.get("offset", 0),
                    limit=tool_call.input.get("limit", 2000),
                )
            elif tool_name == "write_file":
                output = await self._executor.write_file(
                    path=tool_call.input.get("path", ""),
                    content=tool_call.input.get("content", ""),
                )
            elif tool_name == "consult_agent":
                output = await self._executor.consult_agent(
                    agent_slug=tool_call.input.get("agent_slug", ""),
                    question=tool_call.input.get("question", ""),
                    context=tool_call.input.get("context", ""),
                )
            elif tool_name == "read_personality":
                output = await self._executor.read_personality()
            elif tool_name == "write_personality":
                output = await self._executor.write_personality(
                    personality=tool_call.input.get("personality", ""),
                    reason=tool_call.input.get("reason", ""),
                )
            elif tool_name == "write_journal":
                output = await self._executor.write_journal(
                    content=tool_call.input.get("content", ""),
                    entry_type=tool_call.input.get("entry_type", "observation"),
                )
            elif tool_name == "read_journal":
                output = await self._executor.read_journal(
                    days_back=tool_call.input.get("days_back", 7),
                )
            elif tool_name == "search_journal":
                output = await self._executor.search_journal(
                    query=tool_call.input.get("query", ""),
                    days_back=tool_call.input.get("days_back", 30),
                )
            elif tool_name == "write_user_context":
                output = await self._executor.write_user_context(
                    user_context=tool_call.input.get("user_context", ""),
                )
            elif tool_name == "read_user_context":
                output = await self._executor.read_user_context()
            elif tool_name == "mark_memory_relevant":
                output = await self._executor.mark_memory_relevant(
                    memory_uuid=tool_call.input.get("memory_uuid", ""),
                )
            elif tool_name == "mark_memory_irrelevant":
                output = await self._executor.mark_memory_irrelevant(
                    memory_uuid=tool_call.input.get("memory_uuid", ""),
                )
            elif tool_name == "send_push":
                output = await self._executor.send_push(
                    title=tool_call.input.get("title", ""),
                    body=tool_call.input.get("body", ""),
                    url=tool_call.input.get("url"),
                    severity=tool_call.input.get("severity", "info"),
                    tag=tool_call.input.get("tag"),
                )
            elif tool_name == "submit_onboarding":
                output = await self._executor.submit_onboarding(
                    summary=tool_call.input.get("summary", ""),
                )
            # Scheduling tools
            elif tool_name == "schedule_job":
                output = await self._executor.schedule_job(
                    name=tool_call.input.get("name", ""),
                    schedule_type=tool_call.input.get("schedule_type", ""),
                    schedule_value=tool_call.input.get("schedule_value", ""),
                    payload_message=tool_call.input.get("payload_message", ""),
                    payload_type=tool_call.input.get("payload_type", "agent_turn"),
                    delivery=tool_call.input.get("delivery", "none"),
                    timezone=tool_call.input.get("timezone", "UTC"),
                )
            elif tool_name == "list_scheduled_jobs":
                output = await self._executor.list_scheduled_jobs(
                    include_disabled=tool_call.input.get("include_disabled", False),
                )
            elif tool_name == "cancel_scheduled_job":
                output = await self._executor.cancel_scheduled_job(
                    job_id=tool_call.input.get("job_id", ""),
                    hard_delete=tool_call.input.get("hard_delete", False),
                )
            # Subagent steering tools
            elif tool_name == "steer_consultation":
                output = await self._executor.steer_consultation(
                    session_id=tool_call.input.get("session_id", ""),
                    message=tool_call.input.get("message", ""),
                )
            elif tool_name == "list_consultations":
                output = await self._executor.list_consultations(
                    hours_back=tool_call.input.get("hours_back", 24),
                    agent_slug=tool_call.input.get("agent_slug"),
                )
            elif tool_name == "cancel_consultation":
                output = await self._executor.cancel_consultation(
                    session_id=tool_call.input.get("session_id", ""),
                )
            # Task orchestration
            elif tool_name == "manage_tasks":
                output = await self._executor.manage_tasks(
                    action=tool_call.input.get("action", ""),
                    task_id=tool_call.input.get("task_id"),
                    title=tool_call.input.get("title"),
                    description=tool_call.input.get("description"),
                    priority=tool_call.input.get("priority", 2),
                    task_type=tool_call.input.get("task_type", "task"),
                    labels=tool_call.input.get("labels"),
                )
            # Model management
            elif tool_name == "manage_model_config":
                output = await self._executor.manage_model_config(
                    action=tool_call.input.get("action", ""),
                    model_id=tool_call.input.get("model_id"),
                    agent_slug=tool_call.input.get("agent_slug"),
                    primary_model_id=tool_call.input.get("primary_model_id"),
                    fallback_models=tool_call.input.get("fallback_models"),
                    escalation_model_id=tool_call.input.get("escalation_model_id"),
                    temperature=tool_call.input.get("temperature"),
                    thinking_level=tool_call.input.get("thinking_level"),
                    change_reason=tool_call.input.get("change_reason"),
                )
            # Agent performance tracking
            elif tool_name == "log_agent_performance":
                output = await self._executor.log_agent_performance(
                    agent_slug=tool_call.input.get("agent_slug", ""),
                    model_id=tool_call.input.get("model_id", ""),
                    feedback_type=tool_call.input.get("feedback_type", ""),
                    content=tool_call.input.get("content", ""),
                    outcome=tool_call.input.get("outcome", "success"),
                    task_type=tool_call.input.get("task_type"),
                    project_id=tool_call.input.get("project_id"),
                    session_id=tool_call.input.get("session_id"),
                    duration_ms=tool_call.input.get("duration_ms"),
                    input_tokens=tool_call.input.get("input_tokens"),
                    output_tokens=tool_call.input.get("output_tokens"),
                    tool_calls_count=tool_call.input.get("tool_calls_count"),
                    turns=tool_call.input.get("turns"),
                )
            elif tool_name == "review_agent_performance":
                output = await self._executor.review_agent_performance(
                    agent_slug=tool_call.input.get("agent_slug"),
                    model_id=tool_call.input.get("model_id"),
                    feedback_type=tool_call.input.get("feedback_type"),
                    days_back=tool_call.input.get("days_back", 30),
                    limit=tool_call.input.get("limit", 50),
                )
            else:
                output = f"Unknown tool: {tool_name} (original: {tool_call.name})"

            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=output,
                is_error=output.startswith("Error:"),
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_use_id=tool_call.id,
                content=f"Tool execution error: {e}",
                is_error=True,
                duration_ms=duration_ms,
            )


def _compose_hooks(hooks: list[PreToolUseHook]) -> PreToolUseHook:
    """Compose multiple pre-hooks. First DENY wins.

    Fail-closed: any exception from a hook results in DENY.
    """

    async def _composed(tool_call: ToolCall) -> ToolDecision:
        try:
            for hook in hooks:
                decision = await hook(tool_call)
                if decision == ToolDecision.DENY:
                    return ToolDecision.DENY
            return ToolDecision.ALLOW
        except Exception as e:
            # Fail-closed: deny on any unexpected error
            logger.error("Composed hook error for %s: %s — denying", tool_call.name, e)
            return ToolDecision.DENY

    return _composed


def _create_project_permission_hook(project_id: str) -> PreToolUseHook:
    """Create a pre-hook that checks project permission tier.

    Fail-closed: any exception during permission checking results in DENY.
    """

    async def _hook(tool_call: ToolCall) -> ToolDecision:
        try:
            from app.services.project_permission_service import check_tool_allowed

            allowed, reason = await check_tool_allowed(project_id, tool_call.name)
            if not allowed:
                logger.info("Project permission DENY: %s for %s (%s)", tool_call.name, project_id, reason)
                return ToolDecision.DENY
            return ToolDecision.ALLOW
        except Exception as e:
            # Fail-closed: deny on any unexpected error
            logger.error(
                "Project permission hook error for %s/%s: %s — denying",
                project_id, tool_call.name, e,
            )
            return ToolDecision.DENY

    return _hook


def create_direct_handler(
    working_dir: str | None = None,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> DirectToolHandler:
    """Create a direct tool handler with optional permission checking.

    Composes hooks in order: project permission first, then config-based
    permission. First DENY wins.

    Args:
        working_dir: Base directory for tool operations
        permission_config: Optional PermissionConfig as dict (mode, allow_list, etc.)
        project_id: Project ID for agent consultation (enables consult_agent tool)

    Returns:
        DirectToolHandler configured for the directory with permission hook
    """
    hooks: list[PreToolUseHook] = []

    # Project permission hook (tier-based) — checked first
    if project_id:
        hooks.append(_create_project_permission_hook(project_id))

    # Existing per-request permission config hook
    if permission_config:
        from app.services.tools.permissions import PermissionChecker, PermissionConfig

        config = PermissionConfig.from_dict(permission_config)
        checker = PermissionChecker(config)
        hooks.append(checker.create_hook())
        logger.info(f"Created tool handler with permission mode: {config.mode.value}")

    pre_hook: PreToolUseHook | None = None
    if len(hooks) == 1:
        pre_hook = hooks[0]
    elif len(hooks) > 1:
        pre_hook = _compose_hooks(hooks)

    return DirectToolHandler(working_dir, pre_hook=pre_hook, project_id=project_id)
