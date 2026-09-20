"""Cleanup operations for memory system."""

from __future__ import annotations

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_json

from ._api_paths import MEMORY_CLEANUP_ORPHANED_PATH, MEMORY_CLEANUP_PATH
from .memory_api import agent_hub_request
from .memory_formatters import format_orphaned_cleanup_compact, format_stale_cleanup_compact


def _cleanup_orphaned(
    out: OutputContext,
    scope: str,
    scope_id: str | None,
) -> None:
    """Remove orphaned episodes (not linked to any session)."""
    result = agent_hub_request(
        "POST",
        MEMORY_CLEANUP_ORPHANED_PATH,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory cleanup --orphaned",
    )

    if out.is_compact:
        format_orphaned_cleanup_compact(result)
    else:
        output_json(result)


def _cleanup_stale(
    out: OutputContext,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    """Remove stale episodes based on TTL."""
    result = agent_hub_request(
        "POST",
        f"{MEMORY_CLEANUP_PATH}?ttl_days={ttl_days}",
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory cleanup --stale",
    )

    if out.is_compact:
        format_stale_cleanup_compact(result)
    else:
        output_json(result)


def cleanup_impl(
    out: OutputContext,
    orphaned: bool,
    stale: bool,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    """Clean up orphaned or stale episodes."""
    if not orphaned and not stale:
        typer.echo("Error: Must specify --orphaned and/or --stale")
        raise typer.Exit(1)

    if orphaned:
        _cleanup_orphaned(out, scope, scope_id)

    if stale:
        _cleanup_stale(out, ttl_days, scope, scope_id)
