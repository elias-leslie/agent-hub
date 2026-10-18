"""Git context helpers for codex-session-sync."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib import error, parse, request

GIT_LOG_SINCE = "12 hours ago"
GIT_LOG_LIMIT = 10
GIT_FILTER_PREFIXES = ("chore: auto-fix", "chore(.index")
PROJECT_IDENTITY_NAME = "project.identity.json"
DEFAULT_SUMMITFLOW_API = "http://localhost:8001/api"
REGISTRY_TIMEOUT_SECONDS = 5


def _load_project_identity(project_path: Path) -> tuple[str, list[str]]:
    manifest_path = project_path / PROJECT_IDENTITY_NAME
    if not manifest_path.exists():
        return project_path.name, []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return project_path.name, []
    project = payload.get("project")
    if not isinstance(project, dict):
        return project_path.name, []

    canonical = str(project.get("id") or project_path.name)
    aliases: list[str] = []
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value or value == canonical or value in aliases:
                continue
            aliases.append(value)
    return canonical, aliases


def build_project_context(cwd: Path) -> dict[str, object] | None:
    try:
        project_dir = subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    project_path = Path(project_dir)
    branch = subprocess.run(
        ["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    raw_log = subprocess.run(
        ["git", "-C", str(project_path), "log", "--oneline",
         f"--since={GIT_LOG_SINCE}", "--no-merges", "--format=%h %s"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_lines = [
        ln for ln in raw_log.splitlines()
        if not any(ln.startswith(p) or p in ln for p in GIT_FILTER_PREFIXES)
    ]
    project_id, project_aliases = _load_project_identity(project_path)
    return {
        "project_dir": project_path,
        "project_id": project_id,
        "project_aliases": project_aliases,
        "branch": branch,
        "repo_root": str(project_path),
        "git_context": "\n".join(git_lines[:GIT_LOG_LIMIT]),
    }


def fetch_registered_project_root(
    project_id: str,
    api_base: str | None = None,
) -> Path | None:
    """Resolve one project's canonical root from SummitFlow's registry API."""
    safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    if not project_id or any(char not in safe_characters for char in project_id):
        return None
    base = (api_base or os.environ.get("ST_API_BASE") or DEFAULT_SUMMITFLOW_API).rstrip("/")
    url = f"{base}/projects/{parse.quote(project_id, safe='')}"
    try:
        with request.urlopen(url, timeout=REGISTRY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    root_path = payload.get("root_path")
    if not isinstance(root_path, str) or not root_path:
        return None
    return Path(root_path).expanduser().resolve()
