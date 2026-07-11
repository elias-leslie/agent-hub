from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, cast

from app.db import async_session
from app.services._persona_crud import get_persona
from app.services.telegram_delivery import send_configured_report
from app.services.workflow_schedule_registry import is_workflow_schedule_enabled

DEFAULT_ST_PATH = "st"
DEFAULT_WORKDIR = Path.cwd()
DEFAULT_TITLE = "Jenny operator status report"


def persona_status_report_skip_reason(
    persona: Any | None,
    *,
    heartbeat_schedule_enabled: bool,
) -> str | None:
    if persona is None:
        return "persona_missing"
    if getattr(persona, "execution_state", "active") != "active":
        return "persona_paused"
    # The daily operator summary is an explicit systemd schedule, independent
    # of autonomous persona heartbeats. Disabling heartbeat work must not also
    # disable host/storage intervention notices or the requested daily report.
    return None


async def status_report_skip_reason() -> str | None:
    async with async_session() as db:
        persona = await get_persona(db)
        heartbeat_enabled = await is_workflow_schedule_enabled("persona_heartbeat", db)
        # Evaluate ORM-backed fields while the session is still open.  The
        # previous implementation returned a detached/expired Persona and made
        # the systemd report job fail before it could send anything.
        return persona_status_report_skip_reason(
            persona,
            heartbeat_schedule_enabled=heartbeat_enabled,
        )


def build_prompt() -> str:
    return (
        "You are Jenny. Produce a Telegram-ready operator status report grounded in live checks.\n"
        "Use tools to inspect the current system before answering. Minimum checks: \n"
        "- st pulse\n"
        "- st sessions ownership\n"
        "- st ready-all --limit 10\n"
        "- st cleanup status --all\n"
        "- cat /var/lib/summitflow-host-guardian/status.json\n"
        "- systemctl list-timers 'summitflow-*' --all --no-pager\n"
        "- df -h / /media/kasadis/Backups\n"
        "- st -P summitflow backup status\n"
        "- st -P summitflow backup veeam status\n"
        "- st -P summitflow docker status\n"
        "- db query \"select schedule_id, enabled, updated_at from workflow_schedule_controls order by schedule_id;\"\n"
        "- db query \"select name, schedule_type, schedule_value, delivery, enabled, last_run_at, next_run_at, run_count from persona_scheduled_jobs order by created_at desc limit 20;\"\n"
        "- db query \"select name, execution_state, heartbeat_interval_minutes from persona order by id;\"\n"
        "Return plain text only. Keep it concise but complete enough for Telegram.\n"
        "Sections required: Overall, Host and drives, Backups, Services, Active work, Recurring processes, Gaps, Next moves.\n"
        "For Gaps, include things that should be wired up but are not, stalled automations, missing delivery paths, disabled schedules, and orphaned cleanup debt.\n"
        "If a command fails or data is missing, say so explicitly inside Gaps instead of guessing.\n"
        "Do not use markdown tables. Prefer short bullets. Max 3000 characters."
    )


def build_complete_command(prompt: str, *, st_path: str = DEFAULT_ST_PATH) -> list[str]:
    return [
        st_path,
        "agent",
        "run",
        "-a",
        "persona",
        "-p",
        "agent-hub",
        "--read-only",
        "--skip-cache",
        "--raw",
        "--message",
        prompt,
    ]


def _run_text(command: list[str], *, workdir: Path, timeout: int = 30) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"
    output = (completed.stdout or completed.stderr).strip()
    return output if completed.returncode == 0 and output else f"failed (exit {completed.returncode})"


def _as_dict(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def build_deterministic_report(*, st_path: str = DEFAULT_ST_PATH, workdir: Path = DEFAULT_WORKDIR) -> str:
    status_path = Path("/var/lib/summitflow-host-guardian/status.json")
    try:
        raw_guardian = json.loads(status_path.read_text(encoding="utf-8"))
        guardian: dict[str, Any] = cast(dict[str, Any], raw_guardian) if isinstance(raw_guardian, dict) else {}
    except (OSError, json.JSONDecodeError):
        guardian = {"status": "unknown", "issues": [{"message": "Host guardian status unavailable"}], "details": {}}

    details = _as_dict(guardian.get("details"))
    root = _as_dict(details.get("root_disk"))
    backup = _as_dict(details.get("backup_disk"))
    containers = _as_dict(details.get("core_containers"))
    raw_issues = guardian.get("issues")
    issues = [item for item in raw_issues if isinstance(item, dict)] if isinstance(raw_issues, list) else []
    issue_text = "; ".join(str(item.get("message") or item.get("code")) for item in issues[:5]) or "none"
    unhealthy = [
        name.replace("summitflow-stack-", "").replace("-1", "")
        for name, item in containers.items()
        if isinstance(item, dict)
        and (item.get("status") != "running" or item.get("health") not in {"healthy", "none"})
    ]

    backup_status = _run_text([st_path, "-P", "summitflow", "backup", "status"], workdir=workdir)
    veeam_status = _run_text([st_path, "-P", "summitflow", "backup", "veeam", "status"], workdir=workdir)
    failed_system = _run_text(["systemctl", "--failed", "--no-legend", "--plain"], workdir=workdir)
    failed_user = _run_text(["systemctl", "--user", "--failed", "--no-legend", "--plain"], workdir=workdir)
    system_failures = 0 if failed_system in {"", "failed (exit 0)"} else len([line for line in failed_system.splitlines() if line.strip()])
    user_failures = 0 if failed_user in {"", "failed (exit 0)"} else len([line for line in failed_user.splitlines() if line.strip()])

    lines = [
        "Overall",
        f"- Host guardian: {guardian.get('status', 'unknown')} (checked {guardian.get('checked_at', 'unknown')})",
        f"- Intervention items: {issue_text}",
        "",
        "Host and drives",
        f"- Root: {root.get('percent_used', '?')}% used, {root.get('free_gib', '?')} GiB free",
        f"- Backup disk: {backup.get('percent_used', '?')}% used, {backup.get('free_gib', '?')} GiB free",
        f"- Btrfs errors: {sum(int(value) for value in _as_dict(details.get('btrfs_device_stats')).values())}",
        f"- SMART devices healthy: {all(_as_dict(item).get('ok') for item in _as_dict(details.get('smart')).values())}",
        "",
        "Backups",
        f"- Managed: {backup_status.splitlines()[-1] if backup_status else 'unknown'}",
        f"- Veeam: {veeam_status.splitlines()[-1] if veeam_status else 'unknown'}",
        "",
        "Services",
        f"- PostgreSQL ready: {details.get('postgres_ready', False)}",
        f"- Core containers: {'healthy' if not unhealthy else 'unhealthy: ' + ', '.join(unhealthy)}",
        f"- Failed units: system={system_failures}, user={user_failures}",
        "",
        "Next moves",
        "- No intervention needed." if guardian.get("status") == "healthy" else "- Review the intervention items above; an immediate Telegram alert was also queued.",
    ]
    return "\n".join(lines)


def extract_report_text(raw_output: str) -> str:
    payload = json.loads(raw_output)
    content = str(payload.get("content") or "").strip()
    if not content:
        raise RuntimeError("empty content from Jenny status report")
    return content


def run_status_completion(*, st_path: str = DEFAULT_ST_PATH, workdir: Path = DEFAULT_WORKDIR) -> str:
    command = build_complete_command(build_prompt(), st_path=st_path)
    completed = subprocess.run(command, cwd=workdir, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(
            f"status completion failed (exit {completed.returncode}): {stderr or 'no stderr'}"
        )
    return extract_report_text(completed.stdout)


async def deliver_report(*, title: str, body: str, dry_run: bool = False) -> int:
    if dry_run:
        print(body)
        return 0
    async with async_session() as db:
        return await send_configured_report(db=db, title=title, body=body)


async def _run(args: argparse.Namespace) -> None:
    if skip_reason := await status_report_skip_reason():
        print(json.dumps({"skipped": True, "reason": skip_reason, "title": args.title}))
        return
    workdir = Path(args.workdir)
    if args.deterministic:
        report = build_deterministic_report(st_path=args.st_path, workdir=workdir)
    else:
        try:
            report = run_status_completion(st_path=args.st_path, workdir=workdir)
        except RuntimeError:
            # The daily status path must remain useful if every LLM provider is
            # unavailable. Native checks and Telegram delivery are sufficient.
            report = build_deterministic_report(st_path=args.st_path, workdir=workdir)
    sent = await deliver_report(title=args.title, body=report, dry_run=args.dry_run)
    if args.dry_run:
        return
    print(json.dumps({"sent_chunks": sent, "title": args.title}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and send a Jenny Telegram status report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--deterministic", action="store_true")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--st-path", default=DEFAULT_ST_PATH)
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    main()
