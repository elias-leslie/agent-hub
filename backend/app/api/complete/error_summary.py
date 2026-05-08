"""Compact error summaries for agent/tool-loop diagnostics."""

from __future__ import annotations

from typing import Any


def _trim(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _tool_result_errors(progress_log: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in progress_log or []:
        status = str(getattr(entry, "status", "") or "")
        message = _trim(getattr(entry, "message", ""))
        for result in getattr(entry, "tool_results", None) or []:
            if not isinstance(result, dict) or not result.get("is_error"):
                continue
            items.append(
                {
                    "kind": "tool_result",
                    "tool": _trim(result.get("name"), 120),
                    "message": message,
                }
            )
        if status == "error" and message:
            items.append({"kind": "progress", "message": message})
    return items


def build_error_summary(
    *,
    execution_status: str | None,
    execution_error: str | None,
    final_finish_reason: str | None,
    progress_log: list[Any] | None = None,
    tool_result_summaries: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return a small failure-first summary, or None when no error signal exists."""
    items: list[dict[str, Any]] = []
    if execution_error:
        items.append({"kind": "execution_error", "message": _trim(execution_error)})
    if execution_status in {"error", "max_turns"}:
        items.append({"kind": "execution_status", "message": _trim(execution_status)})
    if final_finish_reason in {"error", "max_turns", "max_tokens"}:
        items.append({"kind": "finish_reason", "message": _trim(final_finish_reason)})
    items.extend(_tool_result_errors(progress_log or []))
    for summary in tool_result_summaries or []:
        text = _trim(summary)
        if " error:" in text or text.lower().startswith("error:"):
            items.append({"kind": "tool_output", "message": text})

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            str(item.get("kind") or ""),
            str(item.get("tool") or ""),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 8:
            break
    if not deduped:
        return None
    return {"count": len(deduped), "items": deduped}
