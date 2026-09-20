"""Import operations for memory system."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_error

from .memory_batch_import_apply import apply_content_changes, apply_property_updates
from .memory_batch_import_changes import (
    detect_content_changes,
    detect_property_updates,
    fetch_current_episodes,
)
from .memory_batch_import_loaders import load_episodes_from_directory, load_episodes_from_file


def _display_dry_run_results(
    content_changes: list[dict[str, Any]],
    property_updates: list[dict[str, Any]],
) -> None:
    """Display dry run results."""
    typer.echo(
        f"DRY RUN: {len(content_changes)} content changes, {len(property_updates)} property updates"
    )

    if content_changes:
        typer.echo("Content/tier updates (in place):")
        for c in content_changes:
            typer.echo(f"  {c['uuid'][:8]}: content changed")

    if property_updates:
        typer.echo("Property updates (batch):")
        for u in property_updates:
            fields = [k for k in u if k != "uuid"]
            typer.echo(f"  {u['uuid'][:8]}: {', '.join(fields)}")


def _display_import_results(
    out: OutputContext,
    content_success: int,
    content_changes: list[dict[str, Any]],
    content_failed: int,
    prop_updated: int,
    property_updates: list[dict[str, Any]],
    prop_failed: int,
) -> None:
    """Display import results."""
    if out.is_compact:
        typer.echo(
            f"IMPORT:content={content_success}/{len(content_changes)}|props={prop_updated}/{len(property_updates)}"
        )
    else:
        typer.echo(f"Content updates: {content_success}/{len(content_changes)}")
        typer.echo(f"Property updates: {prop_updated}/{len(property_updates)}")
        if content_failed > 0 or prop_failed > 0:
            typer.echo(f"Failed: {content_failed + prop_failed}")


def import_impl(out: OutputContext, input_path: Path, dry_run: bool) -> None:
    """Import episodes from JSON file(s), updating existing episodes."""
    if not input_path.exists():
        output_error(f"Path not found: {input_path}")
        raise typer.Exit(1)

    if input_path.is_dir():
        episodes = load_episodes_from_directory(input_path)
    else:
        episodes = load_episodes_from_file(input_path)

    if not episodes:
        typer.echo("No episodes to import")
        return

    imported_by_uuid = {ep["uuid"]: ep for ep in episodes if ep.get("uuid")}
    current_by_uuid = fetch_current_episodes()

    content_changes = detect_content_changes(imported_by_uuid, current_by_uuid)
    property_updates = detect_property_updates(imported_by_uuid, current_by_uuid, content_changes)

    if dry_run:
        _display_dry_run_results(content_changes, property_updates)
        return

    if not content_changes and not property_updates:
        typer.echo("No updates needed")
        return

    content_success, content_failed = apply_content_changes(content_changes)
    prop_updated, prop_failed = apply_property_updates(property_updates)

    _display_import_results(
        out,
        content_success,
        content_changes,
        content_failed,
        prop_updated,
        property_updates,
        prop_failed,
    )
