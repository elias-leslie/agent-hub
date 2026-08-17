from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from app.db import async_session
from app.services.telegram_delivery import send_configured_report

DEFAULT_EVENTS_PATH = Path("/var/lib/summitflow-host-guardian/events.jsonl")
DEFAULT_STATE_PATH = Path.home() / ".local/state/agent-hub/host-guardian-telegram.json"


def load_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("event_id"):
            events.append(payload)
    return events


def load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def load_last_event_id(path: Path) -> str | None:
    state = load_state(path)
    value = state.get("last_event_id")
    return str(value) if value else None


def pending_events(events: list[dict[str, Any]], last_event_id: str | None) -> list[dict[str, Any]]:
    if last_event_id is None:
        return events
    for index, event in enumerate(events):
        if str(event.get("event_id")) == last_event_id:
            return events[index + 1 :]
    # A rotated event file should not replay an arbitrary backlog.
    return events[-1:]


def format_event(event: dict[str, Any]) -> tuple[str, str] | None:
    status = str(event.get("status") or "unknown")
    previous = event.get("previous_status")
    if status == "healthy" and previous in {None, "healthy"}:
        return None

    if status == "healthy":
        title = "Host recovered"
        headline = f"Recovered from {previous}. Native checks are healthy again."
    elif status == "critical":
        title = "Host intervention required"
        headline = "A critical host/storage/service condition needs attention."
    else:
        title = "Host maintenance warning"
        headline = "A host condition is approaching an intervention threshold."

    lines = [headline, f"Status: {status}", f"Time: {event.get('occurred_at', 'unknown')}"]
    issues = event.get("issues") or []
    if issues:
        lines.append("Issues:")
        for issue in issues[:8]:
            lines.append(f"- {issue.get('message') or issue.get('code') or 'unknown issue'}")
    actions = event.get("actions") or []
    if actions:
        lines.append("Automatic actions:")
        lines.extend(f"- {action}" for action in actions[:8])
    if status != "healthy":
        lines.append("Details: cat /var/lib/summitflow-host-guardian/status.json")
    return title, "\n".join(lines)


def get_alert_key(event: dict[str, Any]) -> str:
    status = str(event.get("status") or "unknown")
    issues = event.get("issues") or []
    codes = sorted([str(issue.get("code") or "unknown") for issue in issues if isinstance(issue, dict)])
    return f"{status}:{','.join(codes)}"


def should_suppress_cooldown(
    event: dict[str, Any],
    state: dict[str, Any],
    now_timestamp: float,
    cooldown_seconds: float = 43200.0,
) -> bool:
    status = str(event.get("status") or "unknown")
    if status == "healthy":
        return False
    key = get_alert_key(event)
    last_notifications = state.get("last_notifications") or {}
    if isinstance(last_notifications, dict) and key in last_notifications:
        try:
            last_time = float(last_notifications[key])
            if now_timestamp - last_time < cooldown_seconds:
                return True
        except (ValueError, TypeError):
            pass
    return False


def update_notification_state(event: dict[str, Any], state: dict[str, Any], now_timestamp: float) -> None:
    status = str(event.get("status") or "unknown")
    if status == "healthy":
        state["last_notifications"] = {}
    else:
        key = get_alert_key(event)
        stored = state.get("last_notifications")
        last_notifs: dict[str, Any] = stored if isinstance(stored, dict) else {}
        last_notifs[key] = now_timestamp
        state["last_notifications"] = last_notifs


def save_state(path: Path, state_payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state_payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_last_event_id(path: Path, event_id: str) -> None:
    state = load_state(path)
    state["last_event_id"] = event_id
    save_state(path, state)


async def deliver(title: str, body: str) -> int:
    async with async_session() as db:
        return await send_configured_report(db=db, title=title, body=body)


async def run_alerts(*, events_path: Path, state_path: Path, dry_run: bool) -> int:
    events = load_events(events_path)
    if not events:
        return 0
    state = load_state(state_path)
    last_event_id = state.get("last_event_id")
    pending = pending_events(events, str(last_event_id) if last_event_id else None)
    sent = 0
    now_ts = time.time()
    for event in pending:
        event_id = str(event["event_id"])
        rendered = format_event(event)
        if rendered is not None:
            title, body = rendered
            if not should_suppress_cooldown(event, state, now_ts):
                if dry_run:
                    print(f"{title}\n\n{body}")
                else:
                    await deliver(title, body)
                update_notification_state(event, state, now_ts)
                sent += 1
        state["last_event_id"] = event_id
        if not dry_run:
            save_state(state_path, state)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Deliver host guardian state changes to Telegram")
    parser.add_argument("--events-path", default=str(DEFAULT_EVENTS_PATH))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sent = asyncio.run(
        run_alerts(
            events_path=Path(args.events_path),
            state_path=Path(args.state_path),
            dry_run=args.dry_run,
        )
    )
    print(json.dumps({"sent": sent}))


if __name__ == "__main__":  # pragma: no cover
    main()
