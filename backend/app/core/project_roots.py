"""Helpers for resolving canonical project roots across the local workspace."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
from functools import lru_cache
from pathlib import Path
from subprocess import TimeoutExpired

from app.utils.safe_subprocess import create_process, run_process

_CANONICAL_WORKSPACE_ROOT = Path(os.environ.get("AGENT_HUB_PROJECTS_ROOT", Path.home() / ".local" / "share" / "agent-hub" / "projects"))
_MANIFEST_NAME = "project.identity.json"
# Registered project ids are slugs (``a-term``, ``WIP``). Requiring a leading
# alphanumeric and no separators keeps an id from becoming a CLI option or a
# path that escapes the canonical workspace root.
_PROJECT_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_REGISTRY_CACHE_SECONDS = 300.0
# After a failed refresh, keep serving the last good registry for this long
# before trying ``st`` again, so a slow registry does not stall every request.
_REGISTRY_RETRY_SECONDS = 30.0
_REGISTRY_TIMEOUT_SECONDS = 5.0
_registry_roots: dict[str, str] | None = None
_registry_loaded_at = 0.0
# Last successfully loaded registry. Unlike ``_registry_roots`` it survives
# invalidation: it is only the fallback when a refresh times out or fails.
_last_good_roots: dict[str, str] | None = None
_registry_retry_after = 0.0
_registry_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


class ProjectRegistryUnavailable(RuntimeError):
    """The canonical SummitFlow project registry could not be read."""


def _fresh_cached_roots(refresh: bool) -> dict[str, str] | None:
    if (
        not refresh
        and _registry_roots is not None
        and time.monotonic() - _registry_loaded_at < _REGISTRY_CACHE_SECONDS
    ):
        return dict(_registry_roots)
    if _last_good_roots is not None and time.monotonic() < _registry_retry_after:
        return dict(_last_good_roots)
    return None


async def get_registered_project_roots(*, refresh: bool = False) -> dict[str, str]:
    """Return the canonical ``st projects`` registry using async subprocess I/O.

    When a refresh times out or fails, the last good registry is served (and
    retried after ``_REGISTRY_RETRY_SECONDS``). ``ProjectRegistryUnavailable``
    is raised only when no registry has ever loaded in this process.
    """
    global _registry_retry_after
    cached = _fresh_cached_roots(refresh)
    if cached is not None:
        return cached
    if _registry_lock.locked() and _last_good_roots is not None:
        # Another request is already refreshing; don't queue behind it.
        return dict(_last_good_roots)

    async with _registry_lock:
        cached = _fresh_cached_roots(refresh)
        if cached is not None:
            return cached
        try:
            return await _load_registered_project_roots()
        except ProjectRegistryUnavailable as exc:
            if _last_good_roots is None:
                raise
            _registry_retry_after = time.monotonic() + _REGISTRY_RETRY_SECONDS
            logger.warning("Serving last good project registry; refresh failed: %s", exc)
            return dict(_last_good_roots)


async def _load_registered_project_roots() -> dict[str, str]:
    global _last_good_roots, _registry_loaded_at, _registry_roots
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
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_REGISTRY_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        if process is not None:
            process.kill()
            await process.communicate()
        raise ProjectRegistryUnavailable(
            f"st projects list timed out after {_REGISTRY_TIMEOUT_SECONDS:g}s"
        ) from exc
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
    _last_good_roots = dict(roots)
    _registry_loaded_at = time.monotonic()
    return dict(roots)


def invalidate_registered_project_roots() -> None:
    """Force the next lookup to re-read the registry.

    The last good registry is kept only as the fallback for a failed refresh.
    """
    global _registry_loaded_at, _registry_retry_after, _registry_roots
    _registry_roots = None
    _registry_loaded_at = 0.0
    _registry_retry_after = 0.0


def is_valid_project_id(project_id: object) -> bool:
    """Return whether ``project_id`` is a registered-project slug."""
    return isinstance(project_id, str) and _PROJECT_ID_PATTERN.fullmatch(project_id) is not None


def _env_override(project_id: str) -> Path | None:
    key = f"{project_id.upper().replace('-', '_')}_ROOT"
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


_ROOT_CACHE_SIZE = 32
_resolved_roots: dict[str, Path | None] = {}
_resolved_roots_lock = threading.Lock()


def clear_project_root_cache() -> None:
    """Forget memoized project roots so the next lookup re-resolves them."""
    _resolved_roots.clear()


def resolve_project_root(project_id: str) -> Path | None:
    """Resolve a project's canonical root via env, `st`, or the Btrfs workspace.

    Results are memoized per id. A cold lookup may run ``st projects root``
    (up to 5s), so async callers use :func:`aresolve_project_root`.
    """
    if not is_valid_project_id(project_id):
        return None
    if project_id in _resolved_roots:
        return _resolved_roots[project_id]
    root = _resolve_project_root_uncached(project_id)
    with _resolved_roots_lock:  # cold lookups may run concurrently in worker threads
        if len(_resolved_roots) >= _ROOT_CACHE_SIZE:
            _resolved_roots.pop(next(iter(_resolved_roots)))
        _resolved_roots[project_id] = root
    return root


async def aresolve_project_root(project_id: str) -> Path | None:
    """Async ``resolve_project_root``: cold lookups run off the event loop."""
    if not is_valid_project_id(project_id):
        return None
    if project_id in _resolved_roots:
        return _resolved_roots[project_id]
    return await asyncio.to_thread(resolve_project_root, project_id)


def _resolve_project_root_uncached(project_id: str) -> Path | None:
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

    # Normalize, then require containment under the workspace root, so an id
    # can never address a path outside it (CodeQL py/path-injection).
    workspace_root = os.path.realpath(_CANONICAL_WORKSPACE_ROOT)
    candidate = os.path.realpath(os.path.join(workspace_root, project_id))
    if candidate.startswith(workspace_root + os.sep) and os.path.exists(candidate):
        return Path(candidate)

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
