"""Apply import changes to memory system."""

from __future__ import annotations

from typing import Any

import typer

from ._api_paths import MEMORY_BATCH_UPDATE_PATH, MEMORY_EPISODE_PATH
from .memory_api import agent_hub_request


def apply_content_changes(content_changes: list[dict[str, Any]]) -> tuple[int, int]:
    """Apply content/tier changes in place. Returns (success, failed)."""
    content_success = 0
    content_failed = 0

    for change in content_changes:
        try:
            update_result = agent_hub_request(
                "PATCH",
                MEMORY_EPISODE_PATH.format(uuid=change['uuid']),
                json={
                    "content": change["new_content"],
                    "injection_tier": change["tier"],
                },
                tool_name="st memory import",
            )
            if not update_result.get("success"):
                typer.echo(f"  {change['uuid'][:8]}: failed to update - {update_result}")
                content_failed += 1
                continue
            typer.echo(f"  {change['uuid'][:8]}: content updated")
            content_success += 1
        except Exception as e:
            typer.echo(f"  {change['uuid'][:8]}: error - {e}")
            content_failed += 1

    return content_success, content_failed


def apply_property_updates(property_updates: list[dict[str, Any]]) -> tuple[int, int]:
    """Apply property updates via batch API. Returns (updated, failed)."""
    if not property_updates:
        return 0, 0

    result = agent_hub_request(
        "POST",
        MEMORY_BATCH_UPDATE_PATH,
        json={"updates": property_updates},
        tool_name="st memory import",
    )
    return result.get("updated", 0), result.get("failed", 0)
