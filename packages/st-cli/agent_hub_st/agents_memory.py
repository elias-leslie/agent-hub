"""Memory-config flag helpers for the Agent Hub agents CLI."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from ._memory_crud_helpers import parse_csv_values


@dataclass
class MemoryFlags:
    memory_enabled: bool | None
    include_mandates: bool | None
    include_guardrails: bool | None
    include_references: bool | None
    continuity_enabled: bool | None
    continuity_max_sessions: int | None
    audience_tags: str | None
    add_audience_tags: str | None
    remove_audience_tags: str | None
    clear_audience_tags: bool
    exclude_tags: str | None
    add_exclude_tags: str | None
    remove_exclude_tags: str | None
    clear_exclude_tags: bool

    def any_set(self) -> bool:
        """Return True when any granular memory-config flag was provided."""
        return any(
            v is not None
            for v in (
                self.memory_enabled, self.include_mandates, self.include_guardrails,
                self.include_references, self.continuity_enabled, self.continuity_max_sessions,
                self.audience_tags, self.add_audience_tags, self.remove_audience_tags,
                self.exclude_tags, self.add_exclude_tags, self.remove_exclude_tags,
            )
        ) or self.clear_audience_tags or self.clear_exclude_tags


def collect_memory_flags(
    *,
    memory_enabled: bool | None,
    include_mandates: bool | None,
    include_guardrails: bool | None,
    include_references: bool | None,
    continuity_enabled: bool | None,
    continuity_max_sessions: int | None,
    audience_tags: str | None,
    add_audience_tags: str | None,
    remove_audience_tags: str | None,
    clear_audience_tags: bool,
    exclude_tags: str | None,
    add_exclude_tags: str | None,
    remove_exclude_tags: str | None,
    clear_exclude_tags: bool,
) -> MemoryFlags:
    """Collect memory-related CLI flags into a MemoryFlags dataclass."""
    return MemoryFlags(
        memory_enabled=memory_enabled, include_mandates=include_mandates,
        include_guardrails=include_guardrails, include_references=include_references,
        continuity_enabled=continuity_enabled, continuity_max_sessions=continuity_max_sessions,
        audience_tags=audience_tags, add_audience_tags=add_audience_tags,
        remove_audience_tags=remove_audience_tags, clear_audience_tags=clear_audience_tags,
        exclude_tags=exclude_tags, add_exclude_tags=add_exclude_tags,
        remove_exclude_tags=remove_exclude_tags, clear_exclude_tags=clear_exclude_tags,
    )


def merge_tag_values(
    *,
    current: list[str],
    replace: str | None,
    add: str | None,
    remove: str | None,
    clear: bool,
    label: str,
    output_error: Callable[[str], None],
) -> list[str] | None:
    """Merge tag update flags into one final ordered list."""
    if replace is not None and (add is not None or remove is not None or clear):
        output_error(f"Use either --{label}, --add-{label}, --remove-{label}, or --clear-{label}")
        raise typer.Exit(1)
    if clear and (add is not None or remove is not None):
        output_error(f"Use either --clear-{label} or add/remove flags, not both")
        raise typer.Exit(1)
    if replace is not None:
        return parse_csv_values(replace) or []
    if clear:
        return []
    if add is None and remove is None:
        return None
    merged = list(current)
    for tag in parse_csv_values(add) or []:
        if tag not in merged:
            merged.append(tag)
    for tag in parse_csv_values(remove) or []:
        if tag in merged:
            merged.remove(tag)
    return merged


def build_memory_config_patch(
    slug: str,
    flags: MemoryFlags,
    *,
    agents_api: Callable[..., dict[str, Any]],
    output_error: Callable[[str], None],
) -> dict[str, Any]:
    """Return merged memory_config changes for granular CLI flags."""
    agent = agents_api("GET", f"/{slug}")
    cfg: dict[str, Any] = dict(agent.get("memory_config") or {})

    scalar_map = [
        ("injection_enabled", flags.memory_enabled),
        ("include_mandates", flags.include_mandates),
        ("include_guardrails", flags.include_guardrails),
        ("include_references", flags.include_references),
        ("continuity_enabled", flags.continuity_enabled),
        ("continuity_max_sessions", flags.continuity_max_sessions),
    ]
    for key, val in scalar_map:
        if val is not None:
            cfg[key] = val

    for field, replace, add, remove, clear, label in [
        ("audience_tags", flags.audience_tags, flags.add_audience_tags,
         flags.remove_audience_tags, flags.clear_audience_tags, "audience-tags"),
        ("exclude_tags", flags.exclude_tags, flags.add_exclude_tags,
         flags.remove_exclude_tags, flags.clear_exclude_tags, "exclude-tags"),
    ]:
        merged = merge_tag_values(
            current=[str(t) for t in cfg.get(field) or []],
            replace=replace, add=add, remove=remove, clear=clear, label=label,
            output_error=output_error,
        )
        if merged is not None:
            cfg[field] = merged

    return cfg


def resolve_memory_config(
    slug: str,
    flags: MemoryFlags,
    memory_config_file: Path | None,
    clear_memory_config: bool,
    *,
    agents_api: Callable[..., dict[str, Any]],
    load_json_file: Callable[[Path, str], dict[str, Any]],
    output_error: Callable[[str], None],
) -> dict[str, Any] | None | bool:
    """Validate and resolve memory-config flags.

    Returns a dict (new config), None (clear), or False (no change).
    """
    granular = flags.any_set()
    if memory_config_file is not None and clear_memory_config:
        output_error("Use either --memory-config-file or --clear-memory-config, not both")
        raise typer.Exit(1)
    if granular and (memory_config_file is not None or clear_memory_config):
        output_error("Use either granular memory-config flags or --memory-config-file/--clear-memory-config, not both")
        raise typer.Exit(1)
    if memory_config_file is not None:
        return load_json_file(memory_config_file, "Memory config")
    if clear_memory_config:
        return None
    if granular:
        return build_memory_config_patch(
            slug,
            flags,
            agents_api=agents_api,
            output_error=output_error,
        )
    return False
