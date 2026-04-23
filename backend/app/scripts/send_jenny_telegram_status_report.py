from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from app.db import async_session
from app.services.telegram_delivery import send_configured_report

DEFAULT_ST_PATH = "/srv/workspaces/projects/summitflow/backend/.venv/bin/st"
DEFAULT_WORKDIR = Path("/srv/workspaces/projects/agent-hub")
DEFAULT_TITLE = "Jenny operator status report"
DEFAULT_MAX_TURNS = 12


def build_prompt() -> str:
    return (
        "You are Jenny. Produce a Telegram-ready operator status report grounded in live checks.\n"
        "Use tools to inspect the current system before answering. Minimum checks: \n"
        "- st pulse\n"
        "- st sessions ownership\n"
        "- st ready-all --limit 10\n"
        "- st cleanup status --all\n"
        "- db query \"select schedule_id, enabled, updated_at from workflow_schedule_controls order by schedule_id;\"\n"
        "- db query \"select name, schedule_type, schedule_value, delivery, enabled, last_run_at, next_run_at, run_count from persona_scheduled_jobs order by created_at desc limit 20;\"\n"
        "- db query \"select name, execution_state, heartbeat_interval_minutes from persona order by id;\"\n"
        "Return plain text only. Keep it concise but complete enough for Telegram.\n"
        "Sections required: Overall, Active work, Recurring processes, Productivity, Gaps, Next moves.\n"
        "For Gaps, include things that should be wired up but are not, stalled automations, missing delivery paths, disabled schedules, and orphaned cleanup debt.\n"
        "If a command fails or data is missing, say so explicitly inside Gaps instead of guessing.\n"
        "Do not use markdown tables. Prefer short bullets. Max 3000 characters."
    )


def build_complete_command(prompt: str, *, st_path: str = DEFAULT_ST_PATH) -> list[str]:
    return [
        st_path,
        "complete",
        "-a",
        "persona",
        "-p",
        "agent-hub",
        "-x",
        "-n",
        str(DEFAULT_MAX_TURNS),
        "--skip-cache",
        "--raw",
        "--message",
        prompt,
    ]


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
    report = run_status_completion(st_path=args.st_path, workdir=Path(args.workdir))
    sent = await deliver_report(title=args.title, body=report, dry_run=args.dry_run)
    if args.dry_run:
        return
    print(json.dumps({"sent_chunks": sent, "title": args.title}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and send a Jenny Telegram status report")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--st-path", default=DEFAULT_ST_PATH)
    parser.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    main()
