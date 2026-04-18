"""Backup and restore helpers for persona operational tooling."""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable

from app.services.backup_summary import (
    fetch_backup_schedule_line,
    fetch_backup_sources_summary,
    fetch_latest_backup_status_line,
)


def _base_st_cmd(project_id: str | None = None) -> str:
    """Build the base st command prefix with an optional project flag."""
    if project_id:
        return f"st -P {shlex.quote(project_id)}"
    return "st"


def _append_source(cmd: str, source_id: str | None) -> str:
    """Append a source flag when a non-project backup source is targeted."""
    if source_id:
        return f"{cmd} --source {shlex.quote(source_id)}"
    return cmd


def _backup_cmd(
    action: str,
    *,
    project_id: str | None = None,
    source_id: str | None = None,
    backup_id: str | None = None,
    note: str | None = None,
    keep_local: bool = False,
    dry_run: bool = True,
    source_type: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    enable: bool | None = None,
    frequency: str | None = None,
    retention_days: int | None = None,
) -> str:
    """Build a concrete `st backup ...` command string."""
    base = _base_st_cmd(project_id)

    if action == "status":
        return f"{base} backup status"
    if action == "sources":
        cmd = "st backup sources"
        if source_type:
            cmd += f" --type {shlex.quote(source_type)}"
        return cmd
    if action == "list":
        cmd = f"{base} backup list"
        if limit:
            cmd += f" --limit {int(limit)}"
        if status:
            cmd += f" --status {shlex.quote(status)}"
        return _append_source(cmd, source_id)
    if action == "create":
        cmd = f"{base} backup create"
        if note:
            cmd += f" -n {shlex.quote(note)}"
        if keep_local:
            cmd += " --keep-local"
        return _append_source(cmd, source_id)
    if action == "restore":
        if not backup_id:
            raise ValueError("backup_id required for restore")
        cmd = f"{base} backup restore {shlex.quote(backup_id)}"
        if dry_run:
            cmd += " --dry-run"
        return _append_source(cmd, source_id)
    if action == "schedule":
        if not source_id:
            raise ValueError("source_id required for schedule")
        cmd = f"st backup schedule {shlex.quote(source_id)}"
        if enable is True:
            cmd += " --enable"
        elif enable is False:
            cmd += " --disable"
        if frequency:
            cmd += f" --frequency {shlex.quote(frequency)}"
        if retention_days is not None:
            cmd += f" --retention-days {int(retention_days)}"
        return cmd
    raise ValueError(f"Unknown backup action: {action}")


async def manage_backups(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    project_id: str | None = None,
    source_id: str | None = None,
    backup_id: str | None = None,
    note: str | None = None,
    keep_local: bool = False,
    dry_run: bool = True,
    source_type: str | None = None,
    status: str | None = None,
    limit: int = 10,
    enable: bool | None = None,
    frequency: str | None = None,
    retention_days: int | None = None,
) -> str:
    """Query backup state and run carefully-scoped backup operations."""
    if action == "protection_status":
        lines: list[str] = []
        lines.append(await fetch_latest_backup_status_line(project_id))
        target_source = source_id or project_id
        if target_source:
            lines.append(await fetch_backup_schedule_line(target_source))
        else:
            lines.append(await fetch_backup_sources_summary(source_type))
        return "\n---\n".join(line.strip() for line in lines if line and line.strip())

    if action == "schedule" and not source_id:
        return "Error: source_id required for schedule"
    if action == "restore" and not backup_id:
        return "Error: backup_id required for restore"
    if source_id and project_id:
        return "Error: use either project_id or source_id, not both"

    try:
        cmd = _backup_cmd(
            action,
            project_id=project_id,
            source_id=source_id,
            backup_id=backup_id,
            note=note,
            keep_local=keep_local,
            dry_run=dry_run,
            source_type=source_type,
            status=status,
            limit=limit,
            enable=enable,
            frequency=frequency,
            retention_days=retention_days,
        )
    except ValueError as exc:
        return f"Error: {exc}"

    result = await bash_fn(cmd)
    if action == "restore" and not dry_run and "QUEUED" in result:
        return (
            f"{result}\n"
            "Reminder: confirm the queued restore against cleanup status and current task sessions "
            "before assuming the environment is safe to resume."
        )
    return result


__all__ = ["manage_backups"]
