"""Seed memory episodes from skill markdown files.

Reads .md files with YAML frontmatter from a skills/ directory and
upserts them as memory episodes. Uses `skill:<filename>` tag for
idempotent re-seeding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import typer
from st_sdk.output import output_error

from ._api_paths import MEMORY_SAVE_LEARNING_PATH, MEMORY_SEARCH_PATH
from ._memory_crud_helpers import (
    build_save_payload,
    fetch_episode_tags,
    fetch_existing_episode,
    parse_csv_values,
    patch_episode_properties,
    replace_episode_tags,
    update_episode_content_or_tier,
    validate_save_inputs,
    validate_tier,
)
from .memory_api import agent_hub_request

_HUB_TOOL = "st memory seed"

def _parse_fm_value(val: str) -> Any:
    """Parse a single YAML frontmatter value string into a Python type."""
    if val.startswith("[") and val.endswith("]"):
        return [i for i in (s.strip().strip("'\"") for s in val[1:-1].split(",")) if i]
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val.isdigit():
        return int(val)
    return val.strip("'\"")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown text. Returns (frontmatter, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    fm: dict[str, Any] = {}
    for raw in parts[1].strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        fm[key.strip()] = _parse_fm_value(val.strip())
    return fm, parts[2].strip()


def _build_skill_tag(filename: str) -> str:
    """Build a skill tag from filename for idempotent upserts."""
    return f"skill:{Path(filename).stem}"


def _normalize_frontmatter_list(value: Any) -> list[str]:
    """Normalize a frontmatter field into a stable string list."""
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = parse_csv_values(str(value)) or []
    return [item for item in items if item]


def _build_seed_spec(skill_tag: str, content: str, fm: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Build normalized payload and tags for a seeded episode."""
    tier = validate_tier(str(fm.get("tier", "reference")))
    summary = validate_save_inputs(tier, 90, str(fm.get("summary") or skill_tag))
    trigger_types = _normalize_frontmatter_list(fm.get("trigger_task_types"))
    trigger_phases = _normalize_frontmatter_list(fm.get("trigger_phases"))
    tags = _normalize_frontmatter_list(fm.get("tags"))
    if skill_tag not in tags:
        tags.append(skill_tag)

    payload = build_save_payload(
        content=content,
        summary=summary,
        tier=tier,
        confidence=90,
        context=None,
        pinned=bool(fm.get("pinned")),
        trigger_types=",".join(trigger_types) if trigger_types else None,
        trigger_phases=",".join(trigger_phases) if trigger_phases else None,
        context_kind=str(fm.get("context_kind")).strip() if fm.get("context_kind") else None,
        consumer_profiles=",".join(_normalize_frontmatter_list(fm.get("consumer_profiles"))) or None,
        exclude_consumer_profiles=",".join(_normalize_frontmatter_list(fm.get("exclude_consumer_profiles"))) or None,
        agent_slugs=",".join(_normalize_frontmatter_list(fm.get("agent_slugs"))) or None,
        exclude_agent_slugs=",".join(_normalize_frontmatter_list(fm.get("exclude_agent_slugs"))) or None,
        audience_tags=",".join(_normalize_frontmatter_list(fm.get("audience_tags"))) or None,
        exclude_audience_tags=",".join(_normalize_frontmatter_list(fm.get("exclude_audience_tags"))) or None,
        change_reason=None,
    )
    return payload, tags


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _results_bucket(action: str) -> str:
    """Map action labels to results summary buckets."""
    if action == "would_create":
        return "created"
    if action == "would_update":
        return "updated"
    return action


def _find_existing_by_tag(skill_tag: str, scope: str, scope_id: str | None) -> dict[str, Any] | None:
    """Search for an existing episode with the given skill tag."""
    try:
        result = agent_hub_request(
            "GET", MEMORY_SEARCH_PATH, params={"query": skill_tag, "limit": 5},
            scope=scope, scope_id=scope_id, tool_name=_HUB_TOOL,
        )
        for ep in result.get("results", []):
            if skill_tag in ep.get("tags", []):
                return cast(dict[str, Any], ep)
    except Exception:
        pass
    return None


def _upsert_skill_episode(
    skill_tag: str, content: str, frontmatter: dict[str, Any],
    scope: str, scope_id: str | None, dry_run: bool,
) -> str:
    """Upsert a skill episode. Returns action: 'created', 'updated', or 'unchanged'."""
    existing = _find_existing_by_tag(skill_tag, scope, scope_id)
    payload, tags = _build_seed_spec(skill_tag, content, frontmatter)

    if not existing:
        if dry_run:
            return "would_create"
        result = agent_hub_request(
            "POST",
            MEMORY_SAVE_LEARNING_PATH,
            json=payload,
            scope=scope,
            scope_id=scope_id,
            tool_name=_HUB_TOOL,
        )
        if tags and result.get("uuid"):
            replace_episode_tags(str(result["uuid"]), tags)
        return "created"

    episode_uuid = str(existing["uuid"])
    existing_full = fetch_existing_episode(episode_uuid)
    existing_tags = fetch_episode_tags(episode_uuid)
    raw_trigger_types = payload.get("trigger_task_types")
    raw_trigger_phases = payload.get("trigger_phases")
    desired_trigger_types = [str(item) for item in raw_trigger_types if item] if isinstance(raw_trigger_types, list) else []
    desired_trigger_phases = [str(item) for item in raw_trigger_phases if item] if isinstance(raw_trigger_phases, list) else []
    desired_pinned = bool(payload.get("pinned", False))
    desired_context_kind = payload.get("context_kind") or "reference"
    raw_applicability = payload.get("applicability")
    desired_applicability = raw_applicability if isinstance(raw_applicability, dict) else None
    content_changed = str(existing_full.get("content", "")).strip() != content.strip()
    tier_changed = str(existing_full.get("injection_tier", "reference")) != str(payload["injection_tier"])
    summary_changed = str(existing_full.get("summary", "")) != str(payload["summary"])
    trigger_types_changed = _string_list(existing_full.get("trigger_task_types")) != desired_trigger_types
    trigger_phases_changed = _string_list(existing_full.get("trigger_phases")) != desired_trigger_phases
    pinned_changed = bool(existing_full.get("pinned", False)) != desired_pinned
    context_kind_changed = (existing_full.get("context_kind") or "reference") != desired_context_kind
    applicability_changed = (existing_full.get("applicability") or {}) != (desired_applicability or {})
    tags_changed = existing_tags != tags

    if not any(
        [
            content_changed,
            tier_changed,
            summary_changed,
            trigger_types_changed,
            trigger_phases_changed,
            pinned_changed,
            context_kind_changed,
            applicability_changed,
            tags_changed,
        ]
    ):
        return "unchanged"

    if dry_run:
        return "would_update"

    if content_changed or tier_changed:
        update_episode_content_or_tier(
            episode_uuid,
            content=content,
            tier=str(payload["injection_tier"]),
        )
    if summary_changed or trigger_types_changed or trigger_phases_changed or pinned_changed or context_kind_changed or applicability_changed:
        patch_episode_properties(
            episode_uuid,
            str(payload["summary"]) if summary_changed else None,
            ",".join(desired_trigger_types) if trigger_types_changed else None,
            ",".join(desired_trigger_phases) if trigger_phases_changed else None,
            desired_pinned if pinned_changed else None,
            str(desired_context_kind) if context_kind_changed else None,
            desired_applicability if applicability_changed else None,
        )
    if tags_changed:
        replace_episode_tags(episode_uuid, tags)
    return "updated"


def _process_md_file(
    md_file: Path, scope: str, scope_id: str | None, dry_run: bool, results: dict[str, int],
) -> None:
    """Process one markdown file and update results counters in place."""
    skill_tag = _build_skill_tag(md_file.name)
    try:
        frontmatter, body = _parse_frontmatter(md_file.read_text())
        if not body.strip():
            typer.echo(f"  SKIP {md_file.name}: empty body")
            return
        action = _upsert_skill_episode(skill_tag, body, frontmatter, scope, scope_id, dry_run)
        typer.echo(f"  {action.upper()} {md_file.name} [{skill_tag}]")
        key = _results_bucket(action)
        results[key] = results.get(key, 0) + 1
    except Exception as e:
        typer.echo(f"  FAILED {md_file.name}: {e}")
        results["failed"] += 1


def seed_impl(
    directory: Path, scope: str, scope_id: str | None, dry_run: bool, project: str | None,
) -> None:
    """Seed memory episodes from markdown files in a directory."""
    if not directory.exists():
        output_error(f"Directory not found: {directory}")
        raise typer.Exit(1)
    if not directory.is_dir():
        output_error(f"Not a directory: {directory}")
        raise typer.Exit(1)
    if project:
        scope, scope_id = "project", project
    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        typer.echo(f"No .md files found in {directory}")
        return
    typer.echo(f"{'DRY RUN: Processing' if dry_run else 'Seeding'} {len(md_files)} files from {directory}")
    results: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for md_file in md_files:
        _process_md_file(md_file, scope, scope_id, dry_run, results)
    prefix = "Dry run complete" if dry_run else "Seed complete"
    typer.echo(
        f"\n{prefix}: {results['created']} created, {results['updated']} updated, "
        f"{results['unchanged']} unchanged, {results['failed']} failed"
    )
