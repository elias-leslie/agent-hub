"""Batch tier update operations for memory system."""

from __future__ import annotations

import json as json_lib
from pathlib import Path
from typing import Any

import typer
from st_sdk.context import OutputContext

from ._api_paths import MEMORY_BATCH_UPDATE_PATH
from .memory_api import agent_hub_request
from .memory_formatters import format_batch_tier_compact


def _parse_tier_updates_from_file(input_file: Path) -> list[dict[str, str]]:
    """Parse tier updates from a JSON file."""
    if not input_file.exists():
        typer.echo(f"Error: File not found: {input_file}")
        raise typer.Exit(1)

    raw_updates = json_lib.loads(input_file.read_text())
    return [
        {"uuid": u["uuid"], "injection_tier": u.get("tier", u.get("injection_tier"))}
        for u in raw_updates
    ]


def _parse_tier_updates_from_json(json_input: str) -> list[dict[str, str]]:
    """Parse tier updates from a JSON string."""
    raw_updates = json_lib.loads(json_input)
    return [
        {"uuid": u["uuid"], "injection_tier": u.get("tier", u.get("injection_tier"))}
        for u in raw_updates
    ]


def _parse_tier_updates_from_uuids(tier: str, uuids: list[str]) -> list[dict[str, str]]:
    """Create tier updates from a list of UUIDs and a tier."""
    return [{"uuid": u, "injection_tier": tier} for u in uuids]


def _display_batch_tier_result(out: OutputContext, result: dict[str, Any]) -> None:
    """Display batch tier update results."""
    if out.is_compact:
        format_batch_tier_compact(result)
        return

    updated: int = result.get("updated", 0)
    total: int = result.get("total", 0)
    failed: int = result.get("failed", 0)

    typer.echo(f"Updated: {updated}/{total}")

    if failed <= 0:
        return

    typer.echo("Failed updates:")
    results: list[dict[str, Any]] = result.get("results", [])
    for r in results:
        if not r.get("success"):
            uuid: str = r.get("uuid", "unknown")
            error: str = r.get("error", "Unknown")
            typer.echo(f"  {uuid[:8]}: {error}")


def batch_tier_impl(
    out: OutputContext,
    input_file: Path | None,
    json_input: str | None,
    tier: str | None,
    uuids: list[str] | None,
) -> None:
    """Update injection tier for multiple episodes via file, JSON, or UUIDs."""
    updates: list[dict[str, str]] = []

    if input_file:
        updates = _parse_tier_updates_from_file(input_file)
    elif json_input:
        updates = _parse_tier_updates_from_json(json_input)
    elif tier and uuids:
        updates = _parse_tier_updates_from_uuids(tier, uuids)
    else:
        typer.echo("Error: Provide --file, --json, or (UUIDs with --tier)")
        raise typer.Exit(1)

    if not updates:
        typer.echo("Error: No updates provided")
        raise typer.Exit(1)

    result = agent_hub_request(
        "POST",
        MEMORY_BATCH_UPDATE_PATH,
        json={"updates": updates},
        tool_name="st memory batch-tier",
    )

    _display_batch_tier_result(out, result)
