"""Cleanup operations for memory system."""

from __future__ import annotations

import typer
from st_sdk.context import OutputContext
from st_sdk.output import output_json

from ._api_paths import MEMORY_CLEANUP_PATH
from .memory_api import agent_hub_request
from .memory_formatters import format_stale_cleanup_compact


def cleanup_impl(
    out: OutputContext,
    stale: bool,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    """Remove stale episodes based on TTL."""
    if not stale:
        typer.echo("Error: Must specify --stale")
        raise typer.Exit(1)

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
