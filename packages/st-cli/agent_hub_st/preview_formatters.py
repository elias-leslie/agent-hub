"""Compact prompt preview formatters for Agent Hub CLI commands."""

from __future__ import annotations

from typing import Any


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _share(section: dict[str, Any]) -> str:
    value = section.get("share_of_total")
    if isinstance(value, int | float):
        return f"{value:.1%}"
    return "-"


def _section_id(section: dict[str, Any]) -> str:
    source_kind = str(section.get("source_kind") or "unknown")
    source_id = str(section.get("source_id") or "-")
    return f"{source_kind}:{source_id}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: max(0, limit - 2)]}.."


def _print_section_table(sections: list[dict[str, Any]]) -> None:
    if not sections:
        return
    print("sections:")
    for section in sections:
        label = _truncate(str(section.get("label") or "Section"), 34)
        source = _truncate(_section_id(section), 38)
        tokens = _as_int(section.get("estimated_tokens"))
        share = _share(section)
        duplicate = section.get("duplicate_of")
        suffix = f" dup={duplicate}" if duplicate else ""
        print(f"  {tokens:>4} tok {share:>5} | {label:<34} | {source}{suffix}")


def _print_budget(preview_data: dict[str, Any]) -> None:
    budget = preview_data.get("prompt_budget")
    if not isinstance(budget, dict):
        total = _as_int(preview_data.get("full_context_estimated_tokens"))
        if total:
            print(f"prompt={total} tok")
        return

    total = _as_int(budget.get("total_estimated_tokens") or preview_data.get("full_context_estimated_tokens"))
    severity = str(budget.get("severity") or "unknown")
    warnings = budget.get("warnings")
    warning_count = _as_int(budget.get("warning_count"), len(warnings) if isinstance(warnings, list) else 0)
    low_yield = _as_int(budget.get("low_yield_estimated_tokens"))
    print(f"prompt={total} tok | severity={severity} | low_yield={low_yield} tok | warnings={warning_count}")

    if isinstance(warnings, list):
        for warning in warnings[:3]:
            print(f"  warn: {warning}")
        if len(warnings) > 3:
            print(f"  warn: +{len(warnings) - 3} more")

    low_yield_sections = budget.get("top_low_yield_sections")
    if isinstance(low_yield_sections, list) and low_yield_sections:
        labels = [
            f"{section.get('label', 'Section')}={_as_int(section.get('estimated_tokens'))}tok"
            for section in low_yield_sections[:3]
            if isinstance(section, dict)
        ]
        if labels:
            print(f"low_yield_top: {', '.join(labels)}")

    dropped = budget.get("dropped_duplicates")
    if isinstance(dropped, list) and dropped:
        print(f"dropped_duplicates={len(dropped)}")


def print_preview_summary(
    preview_data: dict[str, Any],
    mode: str,
    project: str | None,
    phase: str | None,
) -> None:
    """Print token-efficient prompt preview summary without section bodies."""
    sections = preview_data.get("sections") or []
    sections = [s for s in sections if isinstance(s, dict)]
    print(
        f"{preview_data.get('name', 'Agent')} preview | "
        f"mode={preview_data.get('task_type') or mode} | "
        f"sections={len(sections)} | "
        f"mandates={preview_data.get('mandate_count', 0)} | "
        f"guardrails={preview_data.get('guardrail_count', 0)}"
    )
    if project:
        print(f"project={project}")
    if phase:
        print(f"phase={phase}")
    if preview_data.get("memory_query"):
        query = " ".join(str(preview_data["memory_query"]).split())
        print(f"memory_query={_truncate(query, 180)}")
    _print_budget(preview_data)
    _print_section_table(sections)
    loaded = preview_data.get("loaded_memory_uuids")
    if isinstance(loaded, list) and loaded:
        print(f"loaded_memories={len(loaded)}")
    print("detail: add --show-content for section bodies, --full-context-only for raw context, --json for payload")


def print_preview_detail(
    preview_data: dict[str, Any],
    mode: str,
    project: str | None,
    phase: str | None,
    full_context: str,
) -> None:
    """Print full preview detail: header, sections, memory UUIDs, and context."""
    print(
        f"{preview_data.get('name', 'Agent')} preview | "
        f"mode={preview_data.get('task_type') or mode} | "
        f"sections={len(preview_data.get('sections') or [])} | "
        f"mandates={preview_data.get('mandate_count', 0)} | "
        f"guardrails={preview_data.get('guardrail_count', 0)}"
    )
    if project:
        print(f"project={project}")
    if phase:
        print(f"phase={phase}")
    if preview_data.get("memory_query"):
        print(f"memory_query={preview_data['memory_query']}")

    for section in preview_data.get("sections") or []:
        print(
            "\n"
            f"=== {section.get('label', 'Section')} | "
            f"{section.get('placement', 'system')} | "
            f"{section.get('source_kind', 'unknown')} | "
            f"{section.get('source_id', '-')}"
            f" | {section.get('estimated_tokens', 0)} tok ==="
        )
        print(section.get("content", ""))

    if preview_data.get("loaded_memory_uuids"):
        print("\n=== Loaded Memory UUIDs ===")
        for uuid in preview_data["loaded_memory_uuids"]:
            print(uuid)

    print("\n=== Full Context ===")
    print(full_context)
