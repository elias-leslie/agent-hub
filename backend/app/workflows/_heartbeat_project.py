"""Project access and index reading helpers for heartbeat prompts."""

from __future__ import annotations

import logging

from app.workflows._heartbeat_state import _WORKSPACE_BASE

logger = logging.getLogger(__name__)


def _read_project_index(project_id: str) -> dict[str, object] | None:
    """Read and parse a project's .index.yaml, returning None on failure."""
    index_path = _WORKSPACE_BASE / project_id / ".index.yaml"
    if not index_path.is_file():
        return None
    try:
        import yaml

        data = yaml.safe_load(index_path.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        logger.debug("Failed to read project index for %s", project_id, exc_info=True)
        return None


def _read_project_ports(project_id: str) -> str:
    """Read backend/frontend ports from a project's .index.yaml (compact, fail-silent)."""
    data = _read_project_index(project_id)
    if not data:
        return ""
    services = data.get("services", {})
    if not isinstance(services, dict):
        return ""
    backend = services.get("backend_port")
    frontend = services.get("frontend_port")
    if backend and frontend:
        return f"{backend}/{frontend}"
    return ""


def _read_project_api_url(project_id: str) -> str:
    """Read the canonical local API URL for a project from .index.yaml."""
    data = _read_project_index(project_id)
    if not data:
        return ""
    urls = data.get("urls", {})
    if not isinstance(urls, dict):
        return ""
    api_url = urls.get("api")
    return api_url.strip() if isinstance(api_url, str) else ""


async def get_project_access_summary() -> str:
    """Build a compact summary of project access tiers for the heartbeat prompt."""
    from sqlalchemy import text

    from app.db import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "SELECT project_id, permission_tier, auto_exec_enabled"
                    " FROM project_permissions ORDER BY project_id"
                )
            )
            rows = result.fetchall()
    except Exception:
        logger.exception("Failed to fetch project access summary")
        return "Your project access: (unavailable)"

    if not rows:
        return "Your project access: (no projects configured)"

    groups: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        auto = "auto-exec" if row.auto_exec_enabled else "manual"
        label = str(row.project_id)
        workspace_path = _WORKSPACE_BASE / row.project_id
        if workspace_path.is_dir():
            ports = _read_project_ports(row.project_id)
            if ports:
                label = f"{label}({ports})"
        groups.setdefault((str(row.permission_tier), auto), []).append(label)

    lines = ["Project access:"]
    for (tier, auto), project_ids in sorted(groups.items()):
        lines.append(f"- {tier} {auto}: {', '.join(project_ids)}")
    lines.append(f"- local path: {_WORKSPACE_BASE}/<project-id> when present")
    lines.append(
        "Cross-project inspection: use `st` from any directory; no cd or "
        "persona-sandbox-relative paths."
    )
    return "\n".join(lines)


async def get_permitted_project_ids() -> set[str] | None:
    """Return configured non-off project ids for heartbeat prompt filtering.

    Returns None on query failure so callers can fail open instead of dropping
    all git-state signal during a transient DB issue.
    """
    from sqlalchemy import text

    from app.db import async_session

    try:
        async with async_session() as db:
            result = await db.execute(
                text(
                    "SELECT project_id FROM project_permissions"
                    " WHERE permission_tier != 'off' ORDER BY project_id"
                )
            )
            rows = result.fetchall()
    except Exception:
        logger.exception("Failed to fetch permitted project ids for heartbeat prompt")
        return None

    if not rows:
        return None

    return {
        str(row.project_id)
        for row in rows
        if isinstance(row.project_id, str) and row.project_id
    }
