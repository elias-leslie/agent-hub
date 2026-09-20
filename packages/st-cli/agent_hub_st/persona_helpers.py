"""Helper functions for persona CLI commands."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import typer
from st_sdk.output import output_error


def read_file(path: str) -> str:
    """Read content from a file, exiting on missing file."""
    p = Path(path)
    if not p.is_file():
        output_error(f"File not found: {path}")
        raise typer.Exit(1)
    return p.read_text(encoding="utf-8")


def write_file(path: str, content: str) -> None:
    """Write content to a file, exiting on invalid destination."""
    p = Path(path)
    if not p.parent.exists():
        output_error(f"Directory not found: {p.parent}")
        raise typer.Exit(1)
    p.write_text(content, encoding="utf-8")


def api_call(fn: Any, msg: str) -> Any:
    """Call fn(); on exception print msg and exit."""
    try:
        return fn()
    except Exception as e:
        output_error(f"{msg}: {e}")
        raise typer.Exit(1) from e


def edit_text_in_editor(current_text: str, suffix: str = ".md") -> str | None:
    """Open text in $EDITOR via a temp file; return new text or None if unchanged."""
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", encoding="utf-8", delete=False) as f:
        f.write(current_text)
        tmp_path = f.name
    try:
        subprocess.run([editor, tmp_path], check=True)
        new_text = Path(tmp_path).read_text(encoding="utf-8")
        return None if new_text.strip() == current_text.strip() else new_text
    except subprocess.CalledProcessError as e:
        output_error("Editor exited with error")
        raise typer.Exit(1) from e
    finally:
        os.unlink(tmp_path)


def apply_file_and_scalar_fields(
    fields: dict[str, Any],
    heartbeat_instructions: str | None,
    user_context: str | None,
    voice_enabled: bool | None,
    voice_id: str | None,
    heartbeat_interval: int | None,
    session_reset_mode: str | None,
    session_reset_hour: int | None,
    greeting: str | None,
) -> None:
    """Populate fields dict from provided update arguments."""
    if heartbeat_instructions is not None:
        fields["heartbeat_instructions"] = read_file(heartbeat_instructions)
    if user_context is not None:
        fields["user_context"] = read_file(user_context)
    if voice_enabled is not None:
        fields["voice_enabled"] = voice_enabled
    if voice_id is not None:
        fields["voice_id"] = voice_id
    if heartbeat_interval is not None:
        fields["heartbeat_interval_minutes"] = heartbeat_interval
    if session_reset_mode is not None:
        fields["session_reset_mode"] = session_reset_mode
    if session_reset_hour is not None:
        fields["session_reset_hour"] = session_reset_hour
    if greeting is not None:
        fields["greeting"] = greeting


def load_limits_field(fields: dict[str, Any], limits_path: str) -> None:
    """Load a JSON limits file into fields dict."""
    content = read_file(limits_path)
    try:
        fields["limits"] = json.loads(content)
    except json.JSONDecodeError as e:
        output_error(f"Invalid JSON in limits file: {e}")
        raise typer.Exit(1) from e


def print_update_result(result: dict[str, Any], fields: dict[str, Any]) -> None:
    """Print update confirmation with field summaries."""
    print(f"Persona updated (version {result.get('version', '?')})")
    for key, val in fields.items():
        if isinstance(val, str) and len(val) > 50:
            print(f"  {key}: set ({len(val)} chars)")
        else:
            print(f"  {key}: {val}")


def map_hours_to_time_range(hours: int) -> str:
    """Convert a lookback hours integer to an API time_range string."""
    if hours <= 6:
        return "6h"
    if hours <= 24:
        return "24h"
    if hours <= 168:
        return "7d"
    return "30d"


def print_activity_sessions(sessions: list[Any], total: int, time_range: str) -> None:
    """Print formatted activity session list."""
    if not sessions:
        print(f"No activity in last {time_range}")
        return
    print(f"Activity ({len(sessions)}/{total} sessions, {time_range}):")
    for s in sessions:
        ts = s.get("created_at", "?")
        if isinstance(ts, str) and len(ts) > 19:
            ts = ts[:19]
        stype = s.get("session_type", "?")
        summary = s.get("summary_oneliner") or "(no summary)"
        st_status = s.get("status", "?")
        msgs = s.get("message_count", 0)
        print(f"  {ts} | {stype:<11} | {st_status:<10} | {msgs:>3} msgs | {summary[:60]}")
