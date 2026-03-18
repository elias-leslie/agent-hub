"""Issue-marker construction helpers for pulse classification."""

from __future__ import annotations

from datetime import datetime

from app.api.persona.schemas import PersonaIssueMarker, PersonaStreamEventPreview

from ._constants import FILTERABLE_TAGS, ROOT_CAUSE_PRIORITY, TAG_PRIORITY
from ._text_helpers import (
    human_text_from_raw,
    normalize_issue_key,
    primary_value,
)


def fallback_root_cause(tags: set[str]) -> str | None:
    if "instruction_drift" in tags:
        return "workflow"
    if "tool_friction" in tags or "error" in tags or "retries" in tags:
        return "tool"
    if "stalled" in tags or "warning" in tags or "escalation" in tags:
        return "context"
    return "unknown" if tags else None


def build_marker_title(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    raw_command_rule: tuple[str, str, str] | None,
) -> str:
    if raw_command_rule:
        return raw_command_rule[2]
    if "error" in tags and preview.tool_name:
        return f"{preview.tool_name} failed"
    if "tool_friction" in tags and preview.tool_name:
        return f"{preview.tool_name} hit tool friction"
    if "stalled" in tags:
        return "Work stalled waiting on context or follow-up"
    if "escalation" in tags:
        return "Needed manual follow-up"
    if "warning" in tags:
        return "Completed with warnings"
    if preview.tool_name:
        return preview.tool_name
    return preview.event_type.replace("_", " ")


def build_marker_summary(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    title: str,
    excerpt: str | None,
) -> str:
    parts: list[str] = []
    if excerpt and excerpt.lower() != title.lower():
        parts.append(excerpt)
    if not parts:
        if "error" in tags:
            parts.append("The run recorded an explicit failure.")
        elif "tool_friction" in tags:
            parts.append("The tool path wasted turns before progress resumed.")
        elif "stalled" in tags:
            parts.append("The run waited on follow-up or missing context.")
        elif "escalation" in tags:
            parts.append("The run needed manual review or approval.")
        elif "warning" in tags:
            parts.append("The run completed with warnings or blockers.")
        else:
            parts.append(title)
    if "retries" in tags and not any("retry" in part.lower() for part in parts):
        parts.append("The same step had to be retried.")
    return " ".join(dict.fromkeys(parts))


def build_fingerprint(
    preview: PersonaStreamEventPreview,
    tags: set[str],
    root_cause: str | None,
    raw_command_rule: tuple[str, str, str] | None,
) -> str | None:
    if raw_command_rule:
        return f"instruction-drift:{normalize_issue_key(raw_command_rule[0])}"
    if preview.tool_name and ("tool_friction" in tags or "error" in tags or "retries" in tags):
        prefix = "tool-friction" if "tool_friction" in tags else "error"
        return f"{prefix}:{normalize_issue_key(preview.tool_name)}"
    if "stalled" in tags:
        return f"stalled:{root_cause or 'unknown'}"
    if "escalation" in tags:
        return f"escalation:{root_cause or 'unknown'}"
    if "warning" in tags:
        return f"warning:{root_cause or 'unknown'}"
    return None


def build_marker_detail(preview: PersonaStreamEventPreview, excerpt: str | None, command: str | None) -> str | None:
    detail_lines: list[str] = []
    seen: set[str] = set()

    def _append_unique(value: str | None, *, label: str | None = None) -> None:
        if not value:
            return
        normalized = value.strip()
        if not normalized:
            return
        dedupe_key = normalized.lower()
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        detail_lines.append(f"{label}: {normalized}" if label else normalized)

    _append_unique(excerpt)
    _append_unique(command, label="Command")
    _append_unique(human_text_from_raw(preview.content_preview))
    _append_unique(human_text_from_raw(preview.tool_output_preview))
    input_text = human_text_from_raw(preview.tool_input_preview)
    if input_text and (command is None or input_text.strip().lower() != command.strip().lower()):
        _append_unique(input_text, label="Input")

    if not detail_lines:
        return None
    return "\n".join(detail_lines)


def _sort_key_for(values: tuple[str, ...]):
    def _key(item: str) -> int:
        return values.index(item) if item in values else 99
    return _key


def make_issue_marker(
    *,
    event_id: str,
    event_type: str,
    created_at: datetime,
    tool_name: str | None,
    tags: set[str],
    root_causes: set[str],
    title: str,
    summary: str,
    detail: str | None,
    fingerprint: str | None,
) -> PersonaIssueMarker:
    primary_tag = primary_value(tags, TAG_PRIORITY) or "warning"
    primary_root_cause = primary_value(root_causes, ROOT_CAUSE_PRIORITY)
    return PersonaIssueMarker(
        event_id=event_id,
        event_type=event_type,
        created_at=created_at,
        tool_name=tool_name,
        tags=sorted(tags, key=_sort_key_for(FILTERABLE_TAGS)),
        primary_tag=primary_tag,
        root_causes=sorted(root_causes, key=_sort_key_for(ROOT_CAUSE_PRIORITY)),
        primary_root_cause=primary_root_cause,
        title=title,
        summary=summary,
        detail=detail,
        fingerprint=fingerprint,
    )
