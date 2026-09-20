"""Routing synchronization helpers for the Agent Hub agents CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

_ROUTING_MODES = {"manual_locked", "auto_shadow", "auto_canary", "auto"}


def sync_manual_route(
    slug: str,
    *,
    primary_model: str | None,
    fallback_model: list[str] | None,
    escalation_model: str | None,
    routing_mode: str | None,
    change_reason: str | None,
    agents_api: Callable[..., dict[str, Any]],
    output_error: Callable[[str], None],
) -> None:
    """Update the Agent Hub routing mode without creating model override routes."""
    if routing_mode is not None and routing_mode not in _ROUTING_MODES:
        output_error(f"Invalid routing mode: {routing_mode}")
        raise typer.Exit(1)
    if routing_mode is None:
        return

    agents_api("PUT", f"/{slug}/routing", json={"default_routing_mode": routing_mode})
