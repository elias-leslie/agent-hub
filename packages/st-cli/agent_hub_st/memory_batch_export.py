"""Export operations for memory system."""

from __future__ import annotations

import datetime
import json as json_lib
from pathlib import Path
from typing import Any

import typer

from ._api_paths import MEMORY_BATCH_GET_PATH, MEMORY_LIST_PATH
from .memory_api import agent_hub_request

MINIMAL_EXPORT_FIELDS = [
    "uuid",
    "name",
    "content",
    "category",
    "injection_tier",
    "summary",
    "scope",
    "scope_id",
    "pinned",
    "trigger_task_types",
    "tags",
    "auto_inject",
    "display_order",
]
SPLIT_THRESHOLD = 25


def _filter_episode_fields(episode: dict[str, Any], full: bool) -> dict[str, Any]:
    """Filter episode to minimal fields unless full export requested."""
    if full:
        return episode
    return {k: v for k, v in episode.items() if k in MINIMAL_EXPORT_FIELDS}


def _write_export_file(path: Path, episodes: list[dict[str, Any]], full: bool) -> None:
    """Write episodes to a JSON file with metadata."""
    from datetime import UTC

    filtered = [_filter_episode_fields(ep, full) for ep in episodes]
    export_data = {
        "exported_at": datetime.datetime.now(UTC).isoformat(),
        "count": len(filtered),
        "episodes": filtered,
    }
    path.write_text(json_lib.dumps(export_data, indent=2, default=str))


def _fetch_episodes_by_uuids(
    uuids: list[str],
    scope: str,
    scope_id: str | None,
) -> list[dict[str, Any]]:
    """Fetch specific episodes by UUID."""
    result = agent_hub_request(
        "POST",
        MEMORY_BATCH_GET_PATH,
        json={"uuids": uuids},
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory export",
    )
    return list(result.get("episodes", {}).values())


def _fetch_episodes_by_tier(
    tier: str | None,
    scope: str,
    scope_id: str | None,
) -> list[dict[str, Any]]:
    """Fetch all episodes, optionally filtered by tier."""
    params: dict[str, Any] = {"limit": 100}
    if tier:
        params["category"] = tier

    result = agent_hub_request(
        "GET",
        MEMORY_LIST_PATH,
        params=params,
        scope=scope,
        scope_id=scope_id,
        tool_name="st memory export",
    )
    episodes: list[dict[str, Any]] = result.get("episodes", [])

    while result.get("has_more"):
        params["cursor"] = result.get("cursor")
        result = agent_hub_request(
            "GET",
            MEMORY_LIST_PATH,
            params=params,
            scope=scope,
            scope_id=scope_id,
            tool_name="st memory export",
        )
        episodes.extend(result.get("episodes", []))

    return episodes


def _export_to_directory(
    output: Path,
    episodes: list[dict[str, Any]],
    full: bool,
) -> None:
    """Export episodes to a directory, split by tier."""
    output.mkdir(parents=True, exist_ok=True)

    by_tier: dict[str, list[dict[str, Any]]] = {
        "mandate": [],
        "guardrail": [],
        "reference": [],
    }

    for ep in episodes:
        ep_tier = ep.get("category") or ep.get("injection_tier", "reference")
        if ep_tier in by_tier:
            by_tier[ep_tier].append(ep)
        else:
            by_tier["reference"].append(ep)

    files_written = []
    for tier_name, tier_episodes in by_tier.items():
        if not tier_episodes:
            continue

        if len(tier_episodes) <= SPLIT_THRESHOLD:
            file_path = output / f"{tier_name}s.json"
            _write_export_file(file_path, tier_episodes, full)
            files_written.append(f"{tier_name}s.json ({len(tier_episodes)})")
        else:
            for i, chunk_start in enumerate(range(0, len(tier_episodes), SPLIT_THRESHOLD), 1):
                chunk = tier_episodes[chunk_start : chunk_start + SPLIT_THRESHOLD]
                file_path = output / f"{tier_name}s-{i}.json"
                _write_export_file(file_path, chunk, full)
                files_written.append(f"{tier_name}s-{i}.json ({len(chunk)})")

    typer.echo(f"Exported {len(episodes)} episodes to {output}/")
    for f in files_written:
        typer.echo(f"  {f}")


def _export_to_file_or_stdout(
    output: Path | None,
    episodes: list[dict[str, Any]],
    full: bool,
) -> None:
    """Export episodes to a single file or stdout."""
    from datetime import UTC

    filtered = [_filter_episode_fields(ep, full) for ep in episodes]
    export_data = {
        "exported_at": datetime.datetime.now(UTC).isoformat(),
        "count": len(filtered),
        "episodes": filtered,
    }

    json_output = json_lib.dumps(export_data, indent=2, default=str)

    if output:
        output.write_text(json_output)
        typer.echo(f"Exported {len(episodes)} episodes to {output}")
    else:
        typer.echo(json_output)


def export_impl(
    tier: str | None,
    uuids: list[str] | None,
    output: Path | None,
    scope: str,
    scope_id: str | None,
    full: bool = False,
) -> None:
    """Export episodes to JSON file(s) or stdout."""
    if uuids:
        episodes = _fetch_episodes_by_uuids(uuids, scope, scope_id)
    else:
        episodes = _fetch_episodes_by_tier(tier, scope, scope_id)

    if output and output.suffix == "":
        _export_to_directory(output, episodes, full)
    else:
        _export_to_file_or_stdout(output, episodes, full)
