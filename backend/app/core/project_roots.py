"""Helpers for resolving canonical project roots across the local workspace."""

from __future__ import annotations

import json
import os
import shutil
from functools import lru_cache
from pathlib import Path
from subprocess import TimeoutExpired

from app.utils.safe_subprocess import run_process

_CANONICAL_WORKSPACE_ROOT = Path("/srv/workspaces/projects")
_MANIFEST_NAME = "project.identity.json"


def _env_override(project_id: str) -> Path | None:
    key = f"{project_id.upper().replace('-', '_')}_ROOT"
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


@lru_cache(maxsize=16)
def resolve_project_root(project_id: str) -> Path | None:
    """Resolve a project's canonical root via env, `st`, or the Btrfs workspace."""
    override = _env_override(project_id)
    if override and override.exists():
        return override

    st_binary = shutil.which("st")
    if st_binary:
        try:
            result = run_process(
                [st_binary, "projects", "root", project_id],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            resolved = Path(result.stdout.strip()).expanduser().resolve()
            if resolved.exists():
                return resolved

    candidate = (_CANONICAL_WORKSPACE_ROOT / project_id).resolve()
    if candidate.exists():
        return candidate

    manifest_root = _resolve_manifest_root(project_id)
    if manifest_root is not None:
        return manifest_root
    return None


@lru_cache(maxsize=32)
def _resolve_manifest_root(project_id: str) -> Path | None:
    if not _CANONICAL_WORKSPACE_ROOT.exists():
        return None

    for manifest_path in sorted(_CANONICAL_WORKSPACE_ROOT.glob(f"*/{_MANIFEST_NAME}")):
        try:
            payload = json.loads(manifest_path.read_text())
        except Exception:
            continue

        project = payload.get("project")
        if not isinstance(project, dict):
            continue

        aliases = {
            value
            for key in ("id", "repo_name")
            if isinstance((value := project.get(key)), str) and value
        }
        for key in ("legacy_ids", "repo_aliases"):
            values = project.get(key)
            if isinstance(values, list):
                aliases.update(value for value in values if isinstance(value, str) and value)

        if project_id in aliases:
            return manifest_path.parent.resolve()

    return None


@lru_cache(maxsize=1)
def resolve_summitflow_scripts_dir() -> Path | None:
    """Resolve SummitFlow's shared scripts directory."""
    explicit = os.environ.get("SUMMITFLOW_SCRIPTS_DIR", "").strip()
    if explicit:
        scripts_dir = Path(explicit).expanduser().resolve()
        if scripts_dir.exists():
            return scripts_dir

    summitflow_root = _env_override("summitflow") or resolve_project_root("summitflow")
    if summitflow_root:
        scripts_dir = (summitflow_root / "scripts").resolve()
        if scripts_dir.exists():
            return scripts_dir

    rebuild_path = shutil.which("rebuild.sh")
    if rebuild_path:
        resolved = Path(rebuild_path).resolve()
        scripts_dir = resolved.parent if resolved.name == "rebuild.sh" else None
        if scripts_dir and scripts_dir.exists():
            return scripts_dir

    return None
