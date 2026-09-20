"""Import/export functionality for prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from st_sdk.output import output_error, output_json
from st_sdk.state import is_compact

from .prompt_api import prompt_api
from .prompt_formatters import line_count


def export_prompts(
    slug: Annotated[str | None, typer.Argument(help="Prompt slug (omit for all)")] = None,
    output_file: Annotated[Path | None, typer.Option("-o", "--output", help="Output file")] = None,
) -> None:
    """Export prompt(s) to YAML. Use for editing, then re-import."""
    entries = [prompt_api("GET", f"/{slug}")] if slug else prompt_api("GET", "").get("prompts", [])

    export_data = []
    for p in entries:
        entry: dict[str, Any] = {
            "slug": p["slug"],
            "name": p["name"],
            "is_global": p.get("is_global", False),
        }
        if p.get("description"):
            entry["description"] = p["description"]
        entry["content"] = p.get("content", "")
        export_data.append(entry)

    yaml_str = yaml.dump(export_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    if output_file:
        output_file.write_text(yaml_str)
        if is_compact():
            print(f"EXPORTED[{len(export_data)}]:{output_file}")
        else:
            output_json({"exported": len(export_data), "file": str(output_file)})
    else:
        print(yaml_str)


def _apply_entry(entry: dict[str, Any], existing: dict[str, Any], dry_run: bool) -> tuple[int, int, int]:
    """Apply a single prompt entry. Returns (created, updated, skipped)."""
    slug = entry.get("slug")
    if not slug:
        output_error("Entry missing 'slug' — skipping")
        return 0, 0, 0

    content = entry.get("content", "")
    name = entry.get("name", slug)
    is_global = entry.get("is_global", False)
    ex = existing.get(slug)

    if ex and ex.get("content", "").strip() == content.strip():
        return 0, 0, 1


    if dry_run:
        action = "update" if ex else "create"
        print(f"  [{action}] {slug} ({line_count(content)}L)")
        return (0, 1, 0) if ex else (1, 0, 0)

    payload: dict[str, Any] = {"content": content, "name": name, "is_global": is_global}
    if entry.get("description"):
        payload["description"] = entry["description"]
    if ex:
        prompt_api("PUT", f"/{slug}", json=payload)
        return 0, 1, 0
    payload["slug"] = slug
    prompt_api("POST", "", json=payload)
    return 1, 0, 0


def _process_assignments(assignments: list[dict[str, Any]]) -> None:
    """Create missing agent-prompt assignments and report results."""
    assign_created = assign_skipped = 0
    for assignment in assignments:
        agent_slug = assignment.get("agent")
        prompt_slug = assignment.get("prompt")
        role = assignment.get("role", "system")
        priority = assignment.get("priority", 0)

        if not agent_slug or not prompt_slug:
            continue

        try:
            agent_data = prompt_api("GET", f"/agents/{agent_slug}/assignments")
        except SystemExit:
            assign_skipped += 1
            continue

        if any(a.get("prompt", {}).get("slug") == prompt_slug for a in agent_data.get("assignments", [])):
            assign_skipped += 1
            continue

        try:
            prompt_api(
                "POST",
                f"/agents/{agent_slug}/assignments",
                json={"prompt_slug": prompt_slug, "role": role, "priority": priority},
            )
            assign_created += 1
        except SystemExit:
            assign_skipped += 1

    assign_total = assign_created + assign_skipped
    if is_compact():
        print(f"ASSIGN[{assign_total}]:created={assign_created}|skip={assign_skipped}")
    else:
        output_json({"assignments": {"total": assign_total, "created": assign_created, "skipped": assign_skipped}})


def import_prompts(
    file: Annotated[Path, typer.Argument(help="YAML file to import")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without changes")] = False,
) -> None:
    """Import prompts from YAML. Creates if missing, updates if changed."""
    if not file.exists():
        output_error(f"File not found: {file}")
        raise typer.Exit(1)

    entries = yaml.safe_load(file.read_text())
    if not isinstance(entries, list):
        output_error("YAML must be a list of prompt objects")
        raise typer.Exit(1)

    existing_data = prompt_api("GET", "")
    existing = {p["slug"]: p for p in existing_data.get("prompts", [])}

    results = [_apply_entry(entry, existing, dry_run) for entry in entries]
    created, updated, skipped = (sum(x) for x in zip(*results, strict=False)) if results else (0, 0, 0)

    total = created + updated + skipped
    if is_compact():
        print(f"IMPORT[{total}]:created={created}|updated={updated}|skip={skipped}")
    else:
        output_json({"total": total, "created": created, "updated": updated, "skipped": skipped})

    assignments = [a for entry in entries for a in entry.get("assignments", [])]
    if assignments and not dry_run:
        _process_assignments(assignments)
