"""Work context prompt helpers for Work Chats."""

from __future__ import annotations

import json
from typing import Any

from app.services.llm_messages import Message

_LABELS: dict[str, str] = {
    "mode": "mode",
    "preferred_agent_slug": "preferred_agent",
    "explore_policy": "explore_policy",
    "research_policy": "research_policy",
    "verifier_enabled": "verifier_enabled",
    "project_id": "project",
    "project_name": "project_name",
    "task_id": "task",
    "task_title": "task_title",
    "task_summary": "task_summary",
    "feedback_id": "feedback",
    "design_id": "design",
    "artifact_summary": "artifact_summary",
    "surface": "surface",
    "pane_id": "pane",
}


def _is_present(value: Any) -> bool:
    """Return True for a non-None, non-empty scalar value."""
    if value is None:
        return False
    return bool(str(value).strip())


def _format_value(value: Any) -> str:
    """Format a single work-context value for the prompt."""
    if isinstance(value, dict):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _build_lines(data: dict[str, Any]) -> list[str]:
    """Build prompt lines from raw work-context data."""
    lines: list[str] = [
        "<work_context>",
        "Use this as authoritative user-selected work context. Create or link missing project/task records when needed.",
    ]
    for key, label in _LABELS.items():
        value = data.get(key)
        if _is_present(value):
            lines.append(f"{label}: {_format_value(value)}")
    lines.append("</work_context>")
    return lines


def work_context_to_prompt(work_context: Any | None) -> str | None:
    """Render work_context into a compact system prompt block."""
    if work_context is None:
        return None
    data = work_context.model_dump(exclude_none=True) if hasattr(work_context, "model_dump") else dict(work_context)
    if not data:
        return None
    return "\n".join(_build_lines(data))


def inject_work_context_message(messages: list[Message], work_context: Any | None) -> list[Message]:
    prompt = work_context_to_prompt(work_context)
    if not prompt:
        return messages
    return [Message(role="system", content=prompt), *messages]


def inject_work_context_dict(messages: list[dict[str, Any]], work_context: Any | None) -> list[dict[str, Any]]:
    prompt = work_context_to_prompt(work_context)
    if not prompt:
        return messages
    return [{"role": "system", "content": prompt}, *messages]
