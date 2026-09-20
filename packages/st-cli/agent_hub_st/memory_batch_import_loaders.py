"""Episode loading operations for memory import."""

from __future__ import annotations

import json as json_lib
from pathlib import Path
from typing import Any

import typer
from st_sdk.output import output_error


def load_episodes_from_directory(input_path: Path) -> list[dict[str, Any]]:
    """Load all episodes from JSON files in a directory."""
    json_files = sorted(input_path.glob("*.json"))
    if not json_files:
        output_error(f"No .json files found in {input_path}")
        raise typer.Exit(1)

    all_episodes: list[dict[str, Any]] = []
    for json_file in json_files:
        data = json_lib.loads(json_file.read_text())
        all_episodes.extend(data.get("episodes", []))

    typer.echo(
        f"Loaded {len(all_episodes)} episodes from {len(json_files)} files in {input_path}/"
    )
    return all_episodes


def load_episodes_from_file(input_path: Path) -> list[dict[str, Any]]:
    """Load episodes from a single JSON file."""
    data = json_lib.loads(input_path.read_text())
    episodes: list[dict[str, Any]] = data.get("episodes", [])
    return episodes
