#!/usr/bin/env python3
"""Sync Codex transcripts into Agent Hub and close sessions whose Codex process is gone.

Host-side collector owned by Agent Hub (it reads ~/.codex and /proc, which the API
cannot). The scan window and whether the inactive-close pass runs are Agent Hub
session close settings (GET /api/sessions/close-settings, edited on the Sessions page).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request

# Ensure scripts/lib is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent / "lib"))


def _load_symbol(module_name: str, symbol: str) -> Any:
    return getattr(importlib.import_module(module_name), symbol)


load_env_credentials = _load_symbol("codex_sync_credentials", "load_env_credentials")
run_sync = _load_symbol("codex_sync_runner", "run_sync")
resolve_current_transcript = _load_symbol("codex_sync_transcripts", "resolve_current_transcript")

DEFAULT_API = os.environ.get("AGENT_HUB_API", "http://localhost:8003/api")
DEFAULT_SCAN_HOURS = 24
_SOURCE_PATH = str(Path(__file__))


def log(message: str) -> None:
    """Use the caller's streams so systemd applies the host journal policy."""
    timestamp = datetime.now(UTC).isoformat()
    stream = sys.stderr if message.startswith(("[WARN]", "[ERROR]")) else sys.stdout
    print(f"[{timestamp}] {message}", file=stream, flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="Scan recent Codex transcripts")
    parser.add_argument("--transcript", type=Path, help="Sync a specific transcript path")
    parser.add_argument(
        "--recent-hours",
        type=int,
        default=None,
        help="Recent hours to scan (default: the Codex scan window setting)",
    )
    parser.add_argument("--cwd", type=Path, help="Only scan transcripts from this working directory")
    parser.add_argument(
        "--bind-session",
        help="Bind one live Codex thread id to an explicit registered project",
    )
    parser.add_argument(
        "--bind-project",
        help="Registered project id for --bind-session",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Canonical registered project root for --bind-session",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="Close the Agent Hub session after analysis",
    )
    parser.add_argument(
        "--close-inactive",
        action="store_true",
        help="Close synced Codex sessions whose transcript is no longer open by a live Codex process",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Sync even if transcript state is unchanged",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-session success entries in addition to the sync summary",
    )
    return parser.parse_args(argv)


def fetch_close_settings(api_url: str, client_id: str) -> dict[str, Any] | None:
    """Agent Hub's session close settings, or None when Agent Hub does not answer."""
    req = request.Request(
        f"{api_url.rstrip('/')}/sessions/close-settings",
        headers={"X-Client-Id": client_id, "X-Request-Source": "codex-transcript-sync"},
    )
    try:
        with request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - fall back to built-in defaults
        return None
    return payload if isinstance(payload, dict) else None


def apply_close_settings(args: argparse.Namespace, settings: dict[str, Any] | None) -> list[str]:
    """Fill the scan window and inactive-close switch from settings; return notes to log."""
    notes: list[str] = []
    if settings is None:
        notes.append("[WARN] Session close settings unavailable; using defaults")
        settings = {}
    if args.recent_hours is None:
        hours = settings.get("codex_scan_hours")
        args.recent_hours = hours if isinstance(hours, int) and hours > 0 else DEFAULT_SCAN_HOURS
    if args.close_inactive and settings.get("codex_close_inactive_enabled") is False:
        args.close_inactive = False
        notes.append("[INFO] Closing inactive Codex sessions is switched off in session close settings")
    return notes


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    binding_mode = args.bind_session is not None
    synced = 0
    warnings = 0

    def emit(message: str) -> None:
        nonlocal synced, warnings
        if message.startswith("[INFO] Synced session="):
            synced += 1
            if not args.verbose:
                return
        if message.startswith("[WARN]"):
            warnings += 1
        log(message)

    binding_values = (args.bind_session, args.bind_project, args.project_root)
    if any(value is not None for value in binding_values) and not all(
        value is not None for value in binding_values
    ):
        emit(
            "[WARN] Binding requires --bind-session, --bind-project, and --project-root"
        )
        return 2
    if binding_mode:
        try:
            current = resolve_current_transcript()
        except ValueError as exc:
            emit(f"[WARN] {exc}")
            return 2
        if args.bind_session != current.session_id:
            emit("[WARN] --bind-session must match the validated current native Codex thread ID")
            return 2
    if not args.scan and args.transcript is None:
        args.scan = True

    client_id = load_env_credentials()
    if not client_id:
        emit("[WARN] Missing SUMMITFLOW_CLIENT_ID; skipping Codex sync")
        return 2 if binding_mode else 0

    for note in apply_close_settings(args, fetch_close_settings(DEFAULT_API, client_id)):
        emit(note)

    # The runner's verbose flag only emits successful sync events. Collect those
    # events for a compact summary without changing direct CLI verbosity.
    sync_args = argparse.Namespace(**vars(args))
    sync_args.verbose = True
    exit_code = run_sync(
        sync_args,
        api_url=DEFAULT_API,
        client_id=client_id,
        source_path=_SOURCE_PATH,
        log_fn=emit,
    )
    level = "INFO" if exit_code == 0 else "ERROR"
    log(f"[{level}] Codex sync completed status={exit_code} synced={synced} warnings={warnings}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
