"""Backup summary helpers backed by structured SummitFlow API data."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_SUMMITFLOW_PROJECT_ID = "summitflow"
_DEFAULT_HEARTBEAT_BACKUP_PROJECT_ID = "agent-hub"
_DEFAULT_HEARTBEAT_BACKUP_SOURCE_ID = "persona-sandbox"
_WORKSPACE_BASE = Path(os.environ.get("AGENT_HUB_PROJECTS_ROOT", Path.home() / ".local" / "share" / "agent-hub" / "projects"))


def format_backup_size(size_bytes: int | None) -> str:
    """Format bytes to human-readable compact size."""
    if size_bytes is None or size_bytes == 0:
        return "-"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_compact_backup_source(source: dict[str, Any]) -> str:
    """Format a backup source using the compact SummitFlow CLI layout."""
    source_id = str(source.get("id") or "?")[:20].ljust(20)
    source_type = str(source.get("source_type") or "?")[:10].ljust(10)
    enabled = ("enabled" if source.get("enabled") else "disabled")[:8].ljust(8)
    frequency = str(source.get("frequency") or "?")[:8].ljust(8)
    retention = str(source.get("retention_days", "?"))[:4].ljust(4)
    name = str(source.get("name") or "?")
    return f"{source_id} {source_type} {enabled} {frequency} {retention} {name}"


def _read_summitflow_api_url() -> str:
    """Read SummitFlow's canonical local API URL from .index.yaml."""
    index_path = _WORKSPACE_BASE / _SUMMITFLOW_PROJECT_ID / ".index.yaml"
    if not index_path.is_file():
        return ""
    try:
        import yaml

        data = yaml.safe_load(index_path.read_text())
    except Exception:
        logger.debug("Failed to read SummitFlow project index for backup summary", exc_info=True)
        return ""
    if not isinstance(data, dict):
        return ""
    urls = data.get("urls")
    if not isinstance(urls, dict):
        return ""
    api_url = urls.get("api")
    return api_url.strip() if isinstance(api_url, str) else ""


async def _fetch_backup_json(path: str, *, failure_log: str) -> Any:
    """Fetch one SummitFlow backup API payload."""
    api_base = _read_summitflow_api_url()
    if not api_base:
        logger.debug("Missing SummitFlow API URL for backup summary")
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{api_base}{path}")
            response.raise_for_status()
            return response.json()
    except Exception:
        logger.debug(failure_log, exc_info=True)
        return None


async def fetch_latest_backup_status_line(project_id: str | None = None) -> str:
    """Return the compact latest-backup status line for one project."""
    target_project_id = project_id or _DEFAULT_HEARTBEAT_BACKUP_PROJECT_ID
    if not target_project_id:
        return ""
    payload = await _fetch_backup_json(
        f"/projects/{target_project_id}/backups?limit=1",
        failure_log="Failed to fetch backup status from SummitFlow API",
    )
    if not isinstance(payload, dict):
        return ""
    backups = payload.get("backups")
    if not isinstance(backups, list) or not backups:
        return "NO_BACKUPS"
    latest = backups[0] if isinstance(backups[0], dict) else {}
    return (
        f"LATEST {latest.get('id', '?')}|"
        f"{latest.get('status', 'pending')}|"
        f"{format_backup_size(latest.get('size_bytes'))}"
    )


async def fetch_backup_schedule_line(source_id: str | None = None) -> str:
    """Return the compact schedule/source line for one backup source."""
    target_source_id = source_id or _DEFAULT_HEARTBEAT_BACKUP_SOURCE_ID
    if not target_source_id:
        return ""
    payload = await _fetch_backup_json(
        f"/backup-sources/{target_source_id}",
        failure_log="Failed to fetch backup schedule from SummitFlow API",
    )
    if not isinstance(payload, dict):
        return ""
    return format_compact_backup_source(payload)


async def fetch_backup_sources_summary(source_type: str | None = None) -> str:
    """Return the compact source list used by protection-status tooling."""
    query = urlencode({"source_type": source_type}) if source_type else ""
    suffix = f"?{query}" if query else ""
    payload = await _fetch_backup_json(
        f"/backup-sources{suffix}",
        failure_log="Failed to fetch backup sources from SummitFlow API",
    )
    if not isinstance(payload, list):
        return ""
    if not payload:
        return "SOURCES[0]"
    lines = [f"SOURCES[{len(payload)}]"]
    lines.extend(format_compact_backup_source(source) for source in payload if isinstance(source, dict))
    return "\n".join(lines)


__all__ = [
    "fetch_backup_schedule_line",
    "fetch_backup_sources_summary",
    "fetch_latest_backup_status_line",
    "format_backup_size",
    "format_compact_backup_source",
]
