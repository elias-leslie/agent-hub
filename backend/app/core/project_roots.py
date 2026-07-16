"""Helpers for resolving canonical project roots across the local workspace."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from functools import lru_cache
from pathlib import Path
from subprocess import TimeoutExpired

from app.utils.safe_subprocess import create_process, run_process

_CANONICAL_WORKSPACE_ROOT = Path(os.environ.get("AGENT_HUB_PROJECTS_ROOT", Path.home() / ".local" / "share" / "agent-hub" / "projects"))
_MANIFEST_NAME = "project.identity.json"
_REGISTRY_CACHE_SECONDS = 300.0
_registry_roots: dict[str, str] | None = None
_registry_loaded_at = 0.0
_registry_lock = asyncio.Lock()


class ProjectRegistryUnavailable(RuntimeError):
    """The canonical SummitFlow project registry could not be read."""


async def get_registered_project_roots(*, refresh: bool = False) -> dict[str, str]:
    """Return the canonical ``st projects`` registry using async subprocess I/O."""
    global _registry_loaded_at, _registry_roots
    if (
        not refresh
        and _registry_roots is not None
        and time.monotonic() - _registry_loaded_at < _REGISTRY_CACHE_SECONDS
    ):
        return dict(_registry_roots)

    async with _registry_lock:
        if (
            not refresh
            and _registry_roots is not None
            and time.monotonic() - _registry_loaded_at < _REGISTRY_CACHE_SECONDS
        ):
            return dict(_registry_roots)
        process = None
        try:
            process_env = dict(os.environ)
            # Agent Hub's module path contains a top-level ``app`` package that
            # would shadow SummitFlow's package inside the st executable.
            process_env.pop("PYTHONPATH", None)
            process_env.pop("PYTHONHOME", None)
            process = await create_process(
                "st",
                "projects",
                "list",
                "-v",
                env=process_env,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except TimeoutError as exc:
            if process is not None:
                process.kill()
                await process.communicate()
            raise ProjectRegistryUnavailable(str(exc)) from exc
        except OSError as exc:
            raise ProjectRegistryUnavailable(str(exc)) from exc
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise ProjectRegistryUnavailable(
                f"st projects list failed ({process.returncode}): {detail}"
            )
        try:
            payload = json.loads(stdout.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectRegistryUnavailable("st projects list returned invalid JSON") from exc
        if not isinstance(payload, list):
            raise ProjectRegistryUnavailable("st projects list returned a non-list payload")

        roots: dict[str, str] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            project_id = item.get("id")
            root_path = item.get("root_path")
            if not isinstance(project_id, str) or not project_id.strip():
                continue
            if not isinstance(root_path, str) or not root_path.strip():
                continue
            roots[project_id.strip()] = os.path.realpath(
                os.path.expanduser(root_path.strip())
            )
        if not roots:
            raise ProjectRegistryUnavailable("st projects list returned no project roots")
        _registry_roots = roots
        _registry_loaded_at = time.monotonic()
        return dict(roots)


def invalidate_registered_project_roots() -> None:
    """Clear the async SummitFlow project registry cache."""
    global _registry_loaded_at, _registry_roots
    _registry_roots = None
    _registry_loaded_at = 0.0


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
