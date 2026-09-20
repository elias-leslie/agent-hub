"""Formatting functions for memory command output."""

from __future__ import annotations

from typing import Any

import typer


def _format_meta_line(record: dict[str, Any]) -> str | None:
    """Render compact metadata for list/search/get views."""
    meta_parts: list[str] = []
    if record.get("pinned"):
        meta_parts.append("pinned")

    render_mode = record.get("render_mode")
    if render_mode:
        meta_parts.append(f"render={render_mode}")

    trigger_types = [str(item) for item in record.get("trigger_task_types", []) if item]
    if trigger_types:
        meta_parts.append(f"triggers={','.join(trigger_types)}")

    tags = [str(item) for item in record.get("tags", []) if item]
    if tags:
        preview = ",".join(tags[:3])
        suffix = "+" if len(tags) > 3 else ""
        meta_parts.append(f"tags={preview}{suffix}")

    return " | ".join(meta_parts) if meta_parts else None


def format_stats_compact(stats: dict[str, Any]) -> None:
    """Format memory stats in TOON style."""
    total = stats.get("total", stats.get("total_count", 0))
    by_category = stats.get("by_category", [])
    scope = stats.get("scope") or "global"
    scope_id = stats.get("scope_id")
    scope_label = f"{scope}:{scope_id}" if scope_id else scope

    category_parts = []
    if isinstance(by_category, list):
        for item in by_category:
            cat = item.get("category", "?")
            count = item.get("count", 0)
            category_parts.append(f"{cat}={count}")
    elif isinstance(by_category, dict):
        for cat, count in sorted(by_category.items()):
            category_parts.append(f"{cat}={count}")

    category_str = "|".join(category_parts) if category_parts else "empty"
    print(f"MEMORY[{total}]:scope={scope_label}|{category_str}")


def format_save_compact(result: dict[str, Any]) -> None:
    """Format save result in TOON style."""
    if result.get("is_duplicate"):
        uuid = result.get("reinforced_uuid", "?")
        status = result.get("status", "?")
        print(f"DUPLICATE:{uuid}:{status}")
    elif result.get("uuid"):
        uuid = result.get("uuid", "?")
        status = result.get("status", "?")
        print(f"SAVED:{uuid}:{status}")
    else:
        status = result.get("status", "rejected")
        message = result.get("message", "")
        print(f"REJECTED:{status}:{message}")


def format_list_compact(result: dict[str, Any]) -> None:
    """Format episode list in TOON style."""
    episodes = result.get("episodes", [])
    cursor = result.get("cursor")

    cursor_str = f"cursor={cursor}" if cursor else "cursor=none"
    print(f"EPISODES[{len(episodes)}]:{cursor_str}")

    for ep in episodes:
        uuid = ep.get("uuid", "?")[:8]
        tier = ep.get("category") or ep.get("injection_tier", "?")
        summary = ep.get("summary") or "-"
        content = ep.get("content", "")
        print(f"  {uuid} [{tier}] summary={summary}")
        meta = _format_meta_line(ep)
        if meta:
            print(f"    {meta}")
        print(f"    {content}")


def format_search_compact(result: dict[str, Any]) -> None:
    """Format search results in TOON style."""
    results = result.get("results", [])
    query = result.get("query", "")

    print(f'RESULTS[{len(results)}]:query="{query}"')

    for r in results:
        uuid = r.get("uuid", "?")[:8]
        tier = r.get("category") or r.get("injection_tier", "?")
        score = r.get("relevance_score", 0.0)
        summary = r.get("summary") or "-"
        content = r.get("content", "")
        print(f"  {uuid} [{tier}] {score:.2f} {summary}")
        meta = _format_meta_line(r)
        if meta:
            print(f"    {meta}")
        print(f"    {content}")


def format_get_compact(result: dict[str, Any]) -> None:
    """Format single episode details - shows FULL content for retrieval."""
    uuid_short = result.get("uuid", "")[:8]
    tier = result.get("injection_tier", "unknown")
    content = result.get("content", "")
    helpful = result.get("helpful_count", 0)
    harmful = result.get("harmful_count", 0)
    loaded = result.get("loaded_count", 0)
    summary = result.get("summary")
    trigger_types = result.get("trigger_task_types", [])
    pinned = result.get("pinned", False)
    tags = result.get("tags", [])

    typer.echo(f"{uuid_short} [{tier}] loaded={loaded} helpful={helpful} harmful={harmful}")
    if summary:
        typer.echo(f"Summary: {summary}")
    if trigger_types:
        typer.echo(f"Triggers: {', '.join(trigger_types)}")
    if pinned:
        typer.echo("Pinned: yes")
    render_mode = result.get("render_mode")
    if render_mode:
        typer.echo(f"Render mode: {render_mode}")
    if tags:
        typer.echo(f"Tags: {', '.join(str(tag) for tag in tags)}")
    typer.echo("")
    typer.echo(content)


def format_batch_get_compact(result: dict[str, Any]) -> None:
    """Format batch get results - shows FULL content for each episode."""
    episodes = result.get("episodes", {})
    found = result.get("found", 0)
    missing = result.get("missing", [])

    total_requested = found + len(missing)
    typer.echo(f"GET[{found}/{total_requested}]:missing={len(missing)}")

    for uuid, ep in episodes.items():
        uuid_short = uuid[:8]
        tier = ep.get("injection_tier", "?")
        content = ep.get("content", "")
        helpful = ep.get("helpful_count", 0)
        harmful = ep.get("harmful_count", 0)
        loaded = ep.get("loaded_count", 0)
        summary = ep.get("summary")
        trigger_types = ep.get("trigger_task_types", [])
        tags = ep.get("tags", [])

        typer.echo("")
        typer.echo(f"{uuid_short} [{tier}] loaded={loaded} helpful={helpful} harmful={harmful}")
        if summary:
            typer.echo(f"Summary: {summary}")
        if trigger_types:
            typer.echo(f"Triggers: {', '.join(str(item) for item in trigger_types)}")
        if tags:
            typer.echo(f"Tags: {', '.join(str(tag) for tag in tags)}")
        typer.echo(content)

    if missing:
        typer.echo(f"\nMISSING: {', '.join(u[:8] for u in missing)}")


def format_batch_tier_compact(result: dict[str, Any]) -> None:
    """Format batch tier update in TOON format."""
    updated = result.get("updated", 0)
    total = result.get("total", 0)
    failed = result.get("failed", 0)

    if failed == 0:
        typer.echo(f"BATCH_TIER[{total}]:updated={updated}:OK")
    else:
        typer.echo(f"BATCH_TIER[{total}]:updated={updated}|failed={failed}:PARTIAL")
        for r in result.get("results", []):
            if not r.get("success"):
                typer.echo(f"  FAIL:{r['uuid'][:8]}:{r.get('error', 'unknown')}")


def format_revisions_compact(memory_uuid: str, result: dict[str, Any]) -> None:
    """Format memory revision history in TOON style."""
    revisions = result.get("revisions", [])
    typer.echo(f"REVISIONS[{len(revisions)}]:memory={memory_uuid[:8]}")
    for revision in revisions:
        revision_id = str(revision.get("id", "?"))[:8]
        action = revision.get("action", "?")
        version = revision.get("version", "?")
        created_at = revision.get("created_at", "?")
        changed_by = revision.get("changed_by") or "-"
        change_reason = revision.get("change_reason") or "-"
        typer.echo(
            f"  {revision_id} [{action}] v{version} at={created_at} by={changed_by}"
        )
        typer.echo(f"    reason={change_reason}")
        summary = revision.get("summary")
        if summary:
            typer.echo(f"    summary={summary}")


def format_restore_compact(memory_uuid: str, revision_id: str, result: dict[str, Any]) -> None:
    """Format a successful restore in TOON style."""
    version = result.get("version", "?")
    typer.echo(f"RESTORED:{memory_uuid[:8]}:rev={revision_id[:8]}:version={version}")


def format_orphaned_cleanup_compact(result: dict[str, Any]) -> None:
    """Format orphaned edge cleanup results in TOON style."""
    updated = result.get("edges_updated", 0)
    deleted = result.get("edges_deleted", 0)
    stale_refs = result.get("stale_refs_removed", 0)
    error = result.get("error")

    if error:
        print(f"CLEANUP:FAIL:{error}")
    else:
        print(f"ORPHANED:updated={updated}|deleted={deleted}|stale_refs={stale_refs}")


def format_stale_cleanup_compact(result: dict[str, Any]) -> None:
    """Format stale memory cleanup results in TOON style."""
    deleted = result.get("deleted", 0)
    skipped = result.get("skipped", False)
    reason = result.get("reason")

    if skipped:
        print(f"STALE:SKIP:{reason or 'unknown'}")
    else:
        print(f"STALE:deleted={deleted}")
