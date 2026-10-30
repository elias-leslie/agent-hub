"""Owner notices through Nightshift (notice contract v1: `nightshift push --json`, `nightshift resolve`).

Two conditions reach the owner, each with a stable key that the next good run resolves:
  - a scheduled Agent Hub job run failed (key agent-hub-job-<job>)
  - the retention job could not archive some finished sessions (key agent-hub-retention-archive)
Both are things an agent can look into, so they go to the tray with Look into it, never to the phone.
Sending never raises: a missing or failing nightshift is logged and the caller carries on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.utils.safe_subprocess import create_process

logger = logging.getLogger(__name__)

SOURCE = "agent-hub"
_TIMEOUT_SECONDS = 30
_WORKFLOW_PREFIX = "agent-hub."


def job_key(job: str) -> str:
    return f"agent-hub-job-{job}"


RETENTION_ARCHIVE_KEY = "agent-hub-retention-archive"


def _open_url(path: str) -> str:
    return f"{settings.owner_web_url.rstrip('/')}{path}"


def job_failed_notice(job: str, run_id: str) -> dict[str, Any]:
    notice: dict[str, Any] = {
        "v": 1, "source": SOURCE, "kind": "alert", "severity": "warning", "push": "tray",
        "title": f"Agent Hub job {job} failed",
        "body": f"The scheduled {job} run failed. It tries again on its next schedule.",
        "detail": f"Automation run {run_id}. Its row in Run history on the Automations page has the status and time.",
        "key": job_key(job),
        "open": _open_url("/automations"),
        "fields": [{"label": "Job", "value": job}, {"label": "Run", "value": run_id}],
        "actions": ["look-into", "mute"], "primary": "look-into",
    }
    return notice


def retention_archive_notice(failed: list[str]) -> dict[str, Any]:
    shown = ", ".join(failed[:5]) + (f" and {len(failed) - 5} more" if len(failed) > 5 else "")
    return {
        "v": 1, "source": SOURCE, "kind": "alert", "severity": "warning", "push": "tray",
        "title": "Agent Hub could not archive some old sessions",
        "body": f"{len(failed)} finished sessions kept their raw events because archiving them failed.",
        "detail": f"Sessions: {shown}. The nightly data-retention run left their rows unchanged and retries each night.",
        "key": RETENTION_ARCHIVE_KEY,
        "open": _open_url("/sessions"),
        "fields": [{"label": "Sessions failed", "value": str(len(failed))}],
        "actions": ["look-into", "mute"], "primary": "look-into",
    }


def _nightshift() -> str | None:
    found = shutil.which("nightshift")
    fallback = Path.home() / ".local" / "bin" / "nightshift"
    return found or (str(fallback) if fallback.is_file() else None)


async def _run(args: list[str], stdin: bytes | None = None) -> bool:
    binary = _nightshift()
    if binary is None:
        logger.warning("Owner notice not sent: nightshift is not installed")
        return False
    try:
        proc = await create_process(
            binary, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=_TIMEOUT_SECONDS)
    except (OSError, TimeoutError):
        logger.warning("Owner notice not sent: nightshift %s failed to run", args[0], exc_info=True)
        return False
    if proc.returncode == 2:
        # Exit 2 = the notice breaks the contract: a bug in this module, not a runtime condition.
        logger.error("nightshift %s refused the notice (contract bug): %s", args[0], (err or out).decode(errors="replace").strip())
        return False
    if proc.returncode != 0:
        logger.warning("nightshift %s exited %s: %s", args[0], proc.returncode, (err or out).decode(errors="replace").strip())
        return False
    return True


async def send_notice(notice: dict[str, Any]) -> bool:
    return await _run(["push", "--json"], json.dumps(notice).encode())


async def resolve_notice(key: str, text: str) -> bool:
    return await _run(["resolve", key, "--text", text])


async def _previous_run_failed(workflow_key: str, run_id: str) -> bool:
    from app.db import async_session
    from app.models import AutomationRun

    async with async_session() as db:
        status = (await db.execute(
            select(AutomationRun.status)
            .where(
                AutomationRun.workflow_key == workflow_key,
                AutomationRun.id != run_id,
                AutomationRun.status.in_(("failed", "succeeded")),
            )
            .order_by(AutomationRun.completed_at.desc().nulls_last())
            .limit(1)
        )).scalar_one_or_none()
    return status == "failed"


async def notify_run_settled(run_id: str, workflow_key: str, terminal: str) -> None:
    """Alert on a failed Agent Hub scheduled run; resolve its alert when the next run succeeds."""
    if not workflow_key.startswith(_WORKFLOW_PREFIX) or terminal not in {"failed", "succeeded"}:
        return
    job = workflow_key[len(_WORKFLOW_PREFIX):]
    try:
        if terminal == "failed":
            await send_notice(job_failed_notice(job, run_id))
        elif await _previous_run_failed(workflow_key, run_id):
            await resolve_notice(job_key(job), f"The next {job} run succeeded.")
    except Exception:
        logger.warning("Owner notice for %s run %s failed", workflow_key, run_id, exc_info=True)


async def notify_retention_result(failed: list[str]) -> None:
    """Alert when retention could not archive sessions; resolve once a run archives cleanly."""
    try:
        if failed:
            await send_notice(retention_archive_notice(failed))
        else:
            await resolve_notice(RETENTION_ARCHIVE_KEY, "The latest data-retention run archived every session.")
    except Exception:
        logger.warning("Owner notice for data retention failed", exc_info=True)
