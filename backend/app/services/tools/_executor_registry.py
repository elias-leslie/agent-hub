"""Tool registry builder for direct tool executor.

Assembles the dispatch registry mapping tool names to async callables,
loading sub-module tools lazily to avoid circular imports.
"""

from __future__ import annotations

from typing import Any


async def _manage_model_config(
    action: str,
    model_id: str | None = None,
    agent_slug: str | None = None,
    primary_model_id: str | None = None,
    fallback_models: list[str] | None = None,
    escalation_model_id: str | None = None,
    temperature: float | None = None,
    thinking_level: str | None = None,
    change_reason: str | None = None,
) -> str:
    """Dispatch model management actions to the appropriate handler."""
    from app.services.tools._executor_model_mgmt import (
        get_benchmarks,
        get_model_details,
        list_agents,
        list_models,
        update_agent_model,
    )
    if action == "list_models":
        return await list_models()
    if action == "get_model_details":
        return await get_model_details(model_id)
    if action == "update_agent_model":
        return await update_agent_model(
            agent_slug, primary_model_id, fallback_models,
            escalation_model_id, temperature, thinking_level, change_reason,
        )
    if action == "get_benchmarks":
        return await get_benchmarks()
    if action == "list_agents":
        return await list_agents()
    return (
        f"Error: Unknown action '{action}'. "
        "Use list_models/get_model_details/update_agent_model/get_benchmarks/list_agents."
    )


def _make_manage_tasks_bound(bash_fn: Any) -> Any:
    """Return a manage_tasks callable bound to the given bash function."""
    from app.services.tools._executor_io import manage_tasks

    async def _manage_tasks_bound(
        action: str,
        task_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: int = 2,
        task_type: str = "task",
        labels: str | None = None,
    ) -> str:
        return await manage_tasks(
            bash_fn, action, task_id, title, description, priority, task_type, labels,
        )

    return _manage_tasks_bound


def build_tool_registry(
    project_id: str | None,
    bash_fn: Any,
) -> dict[str, Any]:
    """Build a dispatch registry mapping tool names to async callables.

    Tools that are simple delegates to submodule functions are registered
    here so they do not need to be methods on DirectToolExecutor.
    Tools that require instance state (bash, read_file, write_file,
    consult_agent) remain as class methods and are not in this registry.
    """
    from app.services.tools._executor_consultation import (
        cancel_consultation,
        list_consultations,
        steer_consultation,
    )
    from app.services.tools._executor_io import send_push
    from app.services.tools._executor_performance import (
        log_agent_performance,
        review_agent_performance,
    )
    from app.services.tools._executor_persona import (
        mark_memory_irrelevant,
        mark_memory_relevant,
        read_heartbeat_instructions,
        read_journal,
        read_personality,
        read_user_context,
        search_journal,
        submit_onboarding,
        write_heartbeat_instructions,
        write_journal,
        write_personality,
        write_user_context,
    )
    from app.services.tools._executor_scheduling import (
        cancel_scheduled_job,
        list_scheduled_jobs,
        schedule_job,
    )

    return {
        "steer_consultation": steer_consultation,
        "list_consultations": list_consultations,
        "cancel_consultation": cancel_consultation,
        "log_agent_performance": log_agent_performance,
        "review_agent_performance": review_agent_performance,
        "read_personality": read_personality,
        "write_personality": write_personality,
        "write_journal": write_journal,
        "read_journal": read_journal,
        "search_journal": search_journal,
        "write_user_context": write_user_context,
        "read_user_context": read_user_context,
        "read_heartbeat_instructions": read_heartbeat_instructions,
        "write_heartbeat_instructions": write_heartbeat_instructions,
        "mark_memory_relevant": mark_memory_relevant,
        "mark_memory_irrelevant": mark_memory_irrelevant,
        "submit_onboarding": submit_onboarding,
        "schedule_job": schedule_job,
        "list_scheduled_jobs": list_scheduled_jobs,
        "cancel_scheduled_job": cancel_scheduled_job,
        "send_push": send_push,
        "manage_tasks": _make_manage_tasks_bound(bash_fn),
        "manage_model_config": _manage_model_config,
    }
