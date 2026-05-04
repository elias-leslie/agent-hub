"""Work context prompt helpers for Work Chats."""

from __future__ import annotations

from typing import Any

from app.adapters.base import Message


def work_context_to_prompt(work_context: Any | None) -> str | None:
    """Render work_context into a compact system prompt block."""
    if work_context is None:
        return None
    data = work_context.model_dump(exclude_none=True) if hasattr(work_context, "model_dump") else dict(work_context)
    if not data:
        return None
    labels = {
        "mode": "mode",
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
    lines = [
        "<work_context>",
        "Use this as authoritative user-selected work context. Create or link missing project/task records when needed.",
    ]
    for key, label in labels.items():
        value = data.get(key)
        if value is not None and str(value).strip():
            lines.append(f"{label}: {value}")
    lines.append("</work_context>")
    return "\n".join(lines)


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
