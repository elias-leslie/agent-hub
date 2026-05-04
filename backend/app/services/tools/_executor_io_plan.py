"""Task plan creation helpers for DirectToolExecutor."""

from __future__ import annotations

import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable

from app.services.tools._tool_constants import st_cmd as _st_cmd

logger = logging.getLogger(__name__)

_DEFAULT_COMPLEXITY = "STANDARD"
_DEFAULT_SUBTASK_STEP = "Complete this subtask."
_PLAN_CONTEXT_LIST_FIELDS = ("files_to_modify", "files_to_create", "risks")
_PLAN_ROOT_LIST_FIELDS = ("done_when", "constraints")


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _normalize_references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        url = _clean_text(item.get("url"))
        if title and url:
            normalized.append({"title": title, "url": url})
    return normalized


def _copy_nonempty_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not value:
        return None
    copied = {key: item for key, item in value.items() if isinstance(key, str)}
    return copied or None


def _normalize_step(step: object) -> str | dict[str, object] | None:
    if isinstance(step, str):
        return _clean_text(step)
    if not isinstance(step, dict):
        return None

    description = _clean_text(step.get("description"))
    if not description:
        return None

    normalized: dict[str, object] = {"description": description}
    if spec := _copy_nonempty_dict(step.get("spec")):
        normalized["spec"] = spec
    return normalized


def _normalize_context(context: dict[str, object] | None) -> dict[str, object] | None:
    if not context:
        return None

    normalized: dict[str, object] = {}
    for field in _PLAN_CONTEXT_LIST_FIELDS:
        if values := _normalize_string_list(context.get(field)):
            normalized[field] = values
    if references := _normalize_references(context.get("references")):
        normalized["references"] = references
    if second_opinion := _copy_nonempty_dict(context.get("second_opinion")):
        normalized["second_opinion"] = second_opinion
    return normalized or None


def _normalize_subtask_steps(description: str, raw_steps: object) -> list[str | dict[str, object]]:
    if isinstance(raw_steps, list):
        steps = [step for step in (_normalize_step(step) for step in raw_steps) if step]
        if steps:
            return steps
    return [description.strip() or _DEFAULT_SUBTASK_STEP]


def _normalize_subtask(subtask: object) -> dict[str, object] | None:
    if not isinstance(subtask, dict):
        return None

    subtask_id = _clean_text(subtask.get("id"))
    description = _clean_text(subtask.get("description"))
    if not subtask_id or not description:
        return None

    normalized: dict[str, object] = {"id": subtask_id, "description": description}
    for key in ("phase", "subtask_type"):
        if value := _clean_text(subtask.get(key)):
            normalized[key] = value
    if depends_on := _normalize_string_list(subtask.get("depends_on")):
        normalized["depends_on"] = depends_on
    normalized["steps"] = _normalize_subtask_steps(description, subtask.get("steps"))
    return normalized


def _normalize_subtask_plan(
    subtasks: list[dict[str, object]] | None,
) -> list[dict[str, object]] | None:
    if not subtasks:
        return subtasks
    return [normalized for subtask in subtasks if (normalized := _normalize_subtask(subtask))]


def _split_labels(labels: str | None) -> list[str] | None:
    return labels.split(",") if labels else None


def _base_plan(
    title: str,
    priority: int,
    task_type: str,
    complexity: str | None,
) -> dict[str, object]:
    return {
        "title": title,
        "task_type": task_type,
        "priority": priority,
        "complexity": complexity or _DEFAULT_COMPLEXITY,
        "autonomous": True,
    }


def _optional_plan_fields(
    description: str | None,
    done_when: list[str] | None,
    labels: str | None,
    objective: str | None,
    constraints: list[str] | None,
    spirit_anti: str | None,
    testing_strategy: str | None,
    context: dict[str, object] | None,
    subtasks: list[dict[str, object]] | None,
) -> dict[str, object]:
    fields: dict[str, object] = {}
    scalar_fields = {
        "description": description,
        "objective": _clean_text(objective),
        "spirit_anti": _clean_text(spirit_anti),
        "testing_strategy": _clean_text(testing_strategy),
    }
    fields.update({key: value for key, value in scalar_fields.items() if value})

    list_fields = {
        "done_when": done_when,
        "constraints": _normalize_string_list(constraints),
        "labels": _split_labels(labels),
        "subtasks": _normalize_subtask_plan(subtasks),
    }
    fields.update({key: value for key, value in list_fields.items() if value})

    if normalized_context := _normalize_context(context):
        fields["context"] = normalized_context
    return fields


def _build_plan_json(
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    done_when: list[str] | None,
    labels: str | None,
    complexity: str | None,
    objective: str | None = None,
    constraints: list[str] | None = None,
    spirit_anti: str | None = None,
    testing_strategy: str | None = None,
    context: dict[str, object] | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    plan = _base_plan(title, priority, task_type, complexity)
    plan.update(
        _optional_plan_fields(
            description,
            done_when,
            labels,
            objective,
            constraints,
            spirit_anti,
            testing_strategy,
            context,
            subtasks,
        )
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="st-plan-"
    ) as file_handle:
        json.dump(plan, file_handle)
        return file_handle.name


def _has_plan_payload(
    done_when: list[str] | None,
    complexity: str | None,
    objective: str | None,
    constraints: list[str] | None,
    spirit_anti: str | None,
    testing_strategy: str | None,
    context: dict[str, object] | None,
    subtasks: list[dict[str, object]] | None,
) -> bool:
    return any((done_when, complexity, objective, constraints, spirit_anti, testing_strategy, context, subtasks))


def _basic_create_subcommand(
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
) -> str:
    command = f"create {shlex.quote(title)} -t {shlex.quote(task_type)} -p {priority}"
    if description:
        command += f" -d {shlex.quote(description)}"
    if labels:
        command += f" -l {shlex.quote(labels)}"
    return command


async def _handle_create(
    bash_fn: Callable[..., Awaitable[str]],
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
    project_id: str | None,
    done_when: list[str] | None,
    complexity: str | None,
    objective: str | None = None,
    constraints: list[str] | None = None,
    spirit_anti: str | None = None,
    testing_strategy: str | None = None,
    context: dict[str, object] | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Handle task creation - plan-based or basic."""
    if _has_plan_payload(
        done_when,
        complexity,
        objective,
        constraints,
        spirit_anti,
        testing_strategy,
        context,
        subtasks,
    ):
        tmpfile = _build_plan_json(
            title,
            description,
            priority,
            task_type,
            done_when,
            labels,
            complexity,
            objective=objective,
            constraints=constraints,
            spirit_anti=spirit_anti,
            testing_strategy=testing_strategy,
            context=context,
            subtasks=subtasks,
        )
        cmd = _st_cmd(f"create --plan {shlex.quote(tmpfile)}", project_id)
        logger.info("manage_tasks create via plan: %s", cmd)
        return await bash_fn(cmd)

    cmd = _st_cmd(
        _basic_create_subcommand(title, description, priority, task_type, labels),
        project_id,
    )
    logger.info("manage_tasks create: %s", cmd)
    return await bash_fn(cmd)


__all__ = [
    "_build_plan_json",
    "_handle_create",
]
