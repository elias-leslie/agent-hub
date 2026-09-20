"""Command implementations for memory system.

This module delegates to specialized submodules:
- memory_validation.py: Format standard validation
- memory_crud.py: Basic CRUD operations
- memory_batch.py: Batch operations and import/export
"""

from __future__ import annotations

from pathlib import Path

from st_sdk.context import OutputContext

from .memory_batch import (
    batch_tier_impl,
    cleanup_impl,
    export_impl,
    import_impl,
)
from .memory_crud import (
    delete_impl,
    get_impl,
    list_impl,
    restore_impl,
    revisions_impl,
    save_impl,
    search_impl,
    stats_impl,
    status_impl,
    tag_impl,
    update_impl,
)
from .memory_seed import seed_impl

# Re-export all implementations for backward compatibility
__all__ = [
    "batch_tier_impl",
    "cleanup_impl",
    "delete_impl",
    "export_impl",
    "get_impl",
    "import_impl",
    "list_impl",
    "restore_impl",
    "revisions_impl",
    "save_impl",
    "search_impl",
    "seed_impl",
    "stats_impl",
    "status_impl",
    "tag_impl",
    "update_impl",
]


# These functions are just thin wrappers for backward compatibility
def stats(out: OutputContext, scope: str, scope_id: str | None) -> None:
    """Get memory statistics."""
    stats_impl(out, scope, scope_id)


def save(
    out: OutputContext,
    content: str,
    summary: str,
    tier: str,
    confidence: int,
    context: str | None,
    pinned: bool,
    trigger_types: str | None,
    trigger_phases: str | None,
    context_kind: str | None,
    consumer_profiles: str | None,
    exclude_consumer_profiles: str | None,
    agent_slugs: str | None,
    exclude_agent_slugs: str | None,
    audience_tags: str | None,
    exclude_audience_tags: str | None,
    tags: str | None,
    scope: str,
    scope_id: str | None,
    change_reason: str | None,
    render_mode: str | None = None,
) -> None:
    """Save a new memory episode."""
    save_impl(
        out,
        content,
        summary,
        tier,
        confidence,
        context,
        pinned,
        trigger_types,
        trigger_phases,
        context_kind,
        consumer_profiles,
        exclude_consumer_profiles,
        agent_slugs,
        exclude_agent_slugs,
        audience_tags,
        exclude_audience_tags,
        tags,
        scope,
        scope_id,
        change_reason,
        render_mode=render_mode,
    )


def search(
    out: OutputContext,
    query: str,
    limit: int,
    min_score: float,
    scope: str,
    scope_id: str | None,
) -> None:
    """Search memory episodes."""
    search_impl(out, query, limit, min_score, None, scope, scope_id)


def get(out: OutputContext, uuids: list[str]) -> None:
    """Get memory episode(s) by UUID."""
    get_impl(out, uuids)


def delete(uuids: list[str], *, change_reason: str | None = None) -> None:
    """Delete memory episode(s)."""
    delete_impl(uuids, change_reason=change_reason)


def update(
    uuid: str,
    content: str | None,
    tier: str | None,
    summary: str | None,
    trigger_types: str | None,
    trigger_phases: str | None,
    pinned: bool | None,
    context_kind: str | None,
    consumer_profiles: str | None,
    exclude_consumer_profiles: str | None,
    agent_slugs: str | None,
    exclude_agent_slugs: str | None,
    audience_tags: str | None,
    exclude_audience_tags: str | None,
    clear_applicability: bool,
    tags: str | None,
    clear_tags: bool,
    change_reason: str | None,
    render_mode: str | None = None,
) -> None:
    """Update a memory episode."""
    update_impl(
        uuid,
        content,
        tier,
        summary,
        trigger_types,
        trigger_phases,
        pinned,
        context_kind,
        consumer_profiles,
        exclude_consumer_profiles,
        agent_slugs,
        exclude_agent_slugs,
        audience_tags,
        exclude_audience_tags,
        clear_applicability,
        tags,
        clear_tags,
        change_reason,
        render_mode=render_mode,
    )


def revisions(out: OutputContext, uuid: str, limit: int) -> None:
    """List memory revision history."""
    revisions_impl(out, uuid, limit)


def restore(uuid: str, revision_id: str, change_reason: str | None) -> None:
    """Restore a memory episode revision."""
    restore_impl(uuid, revision_id, change_reason=change_reason)


def batch_tier(
    out: OutputContext,
    input_file: Path | None,
    json_input: str | None,
    tier: str | None,
    uuids: list[str] | None,
) -> None:
    """Batch update episode tiers."""
    batch_tier_impl(out, input_file, json_input, tier, uuids)


def export(
    tier: str | None,
    uuids: list[str] | None,
    output: Path | None,
    scope: str,
    scope_id: str | None,
    full: bool = False,
) -> None:
    """Export memory episodes."""
    export_impl(tier, uuids, output, scope, scope_id, full)


def cleanup(
    out: OutputContext,
    orphaned: bool,
    stale: bool,
    ttl_days: int,
    scope: str,
    scope_id: str | None,
) -> None:
    """Clean up orphaned or stale episodes."""
    cleanup_impl(out, orphaned, stale, ttl_days, scope, scope_id)
