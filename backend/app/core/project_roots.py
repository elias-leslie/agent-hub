"""Helpers for resolving canonical project roots across the local workspace."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

_CANONICAL_WORKSPACE_ROOT = Path("/srv/workspaces/projects")


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
            result = subprocess.run(
                [st_binary, "projects", "root", project_id],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            resolved = Path(result.stdout.strip()).expanduser().resolve()
            if resolved.exists():
                return resolved

    candidate = (_CANONICAL_WORKSPACE_ROOT / project_id).resolve()
    if candidate.exists():
        return candidate
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
