"""Build compact st quick-use memory from recent tool events."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Text, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models import Session, SessionEvent, SessionEventType

logger = logging.getLogger(__name__)

_LOOKBACK = timedelta(days=14)
_QUERY_LIMIT = 250
_CACHE_TTL_SECONDS = 60
_GLOBAL_OPTIONS_WITH_VALUE = {"-P", "--project"}
_HELP_FLAGS = {"-h", "--help"}


@dataclass(frozen=True)
class StUsageQuickEntry:
    """One injected st quick-use line split for UI display."""

    command: str
    description: str
    source: str


@dataclass(frozen=True)
class StUsageCommandMetric:
    """Observed usage metrics for one st command key."""

    command_key: str
    uses: int
    help_lookups: int
    injected_example: str | None = None
    last_seen: str | None = None


@dataclass(frozen=True)
class StUsageMemory:
    """Compact injected memory for st command usage."""

    quick: list[str]
    observed: int
    help_count: int
    generated_at: datetime
    quick_entries: list[StUsageQuickEntry]
    command_metrics: list[StUsageCommandMetric]
    cache_ttl_seconds: int = _CACHE_TTL_SECONDS
    lookback: str = "14d"


@dataclass
class _CommandStats:
    uses: int = 0
    helps: int = 0
    last_seen: datetime | None = None


@dataclass(frozen=True)
class _ParsedStCommand:
    key: str
    is_help: bool


_STATIC_QUICK_USE: dict[str, str] = {
    "pulse": "st pulse --gate | preflight; edit only if clear",
    "queue": "project flag before command: st -P <project> ready --limit N; st feedback list --project <project> --status open --limit N; st sessions ownership -P <project> | queue + lanes",
    "vcs": "st vcs doctor; st jj status | read-only VCS diagnostics",
    "search": 'st search "query" | repo/code discovery',
    "memory search": 'st memory search "query" | rules/history before retries',
    "graph doctor": "st graph doctor --project <project> | Graphify health; auto-refreshes code graph",
    "graph query": 'st graph query "question" --project <project> --budget 1200 | topology map',
    "graph fallow": "st graph fallow audit --project <project> | compact JS/TS audit",
    "check quick": "st check --quick --changed-only | changed repo gates",
    "check full": "st check --check | full repo gates",
    "web research": 'st web research --query "..." | public web verification',
    "agents preview": "st agents preview <slug> --json | prompt/context size",
    "sessions ownership": "st sessions ownership -P <project> | lane truth if blocked",
    "service rebuild": "st service rebuild <project> --detach | rebuild/restart via st",
    "db query": 'st db query -t "SELECT ..." | read DB safely',
    "browser check": "st browser check <url> <png> | UI render verification",
    "vm status": "st vm status <id> | inspect browser/test VM",
    "tools catalog": "st tools catalog | canonical st replacements",
}

_BASE_KEYS = (
    "pulse",
    "queue",
    "vcs",
    "search",
    "memory search",
    "graph doctor",
    "check quick",
    "agents preview",
)
_TASK_KEYS: dict[str, tuple[str, ...]] = {
    "frontend": ("browser check", "check quick"),
    "ui-design": ("browser check", "check quick"),
    "design-review": ("browser check",),
    "database": ("db query",),
    "devops": ("service rebuild", "vm status"),
    "config": ("service rebuild",),
    "verification": ("check full", "browser check"),
}
_CACHE: dict[tuple[str | None, str | None], tuple[datetime, StUsageMemory]] = {}


def _command_from_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("cmd", "command"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped:
            return stripped
    return None


def _strip_prompt(command: str) -> str:
    stripped = command.strip()
    return stripped[1:].strip() if stripped.startswith("$") else stripped


def _find_st_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens):
        if token == "st" or token.endswith("/st"):
            return index
    return None


def _command_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(_strip_prompt(command))
    except ValueError:
        return []
    st_index = _find_st_index(tokens)
    if st_index is None:
        return []
    return tokens[st_index + 1 :]


def _drop_global_options(tokens: list[str]) -> list[str]:
    cleaned: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _GLOBAL_OPTIONS_WITH_VALUE:
            index += 2
            continue
        if token.startswith("--project="):
            index += 1
            continue
        if token in {"--human", "--compact", "--no-compact", "--progress-only"}:
            index += 1
            continue
        cleaned.extend(tokens[index:])
        break
    return cleaned


def parse_st_command(command: str | None) -> _ParsedStCommand | None:
    """Return stable command key for one shell st invocation."""
    if not command:
        return None
    tokens = _drop_global_options(_command_tokens(command))
    if not tokens:
        return None

    is_help = any(token in _HELP_FLAGS for token in tokens)
    command_tokens = [token for token in tokens if token not in _HELP_FLAGS]
    if not command_tokens:
        return None

    top = command_tokens[0]
    rest = command_tokens[1:]
    if top == "check":
        if "--check" in rest:
            return _ParsedStCommand("check full", is_help)
        if "--frontend-only" in rest:
            return _ParsedStCommand("check quick", is_help)
        return _ParsedStCommand("check quick", is_help)

    if top in {
        "agents",
        "browser",
        "db",
        "graph",
        "memory",
        "service",
        "sessions",
        "tools",
        "vm",
        "web",
    }:
        subcommand = next((token for token in rest if not token.startswith("-")), "")
        key = f"{top} {subcommand}".strip()
        return _ParsedStCommand(key, is_help)

    return _ParsedStCommand(top, is_help)


def _seed_keys(task_type: str | None) -> list[str]:
    keys = list(_BASE_KEYS)
    for key in _TASK_KEYS.get(task_type or "", ()):
        if key not in keys:
            keys.append(key)
    return keys


def _split_quick_entry(line: str, *, source: str) -> StUsageQuickEntry:
    command, sep, description = line.partition(" | ")
    return StUsageQuickEntry(
        command=command.strip(),
        description=description.strip() if sep else "",
        source=source,
    )


def _build_command_metric(key: str, stats: _CommandStats) -> StUsageCommandMetric:
    last_seen = stats.last_seen
    return StUsageCommandMetric(
        command_key=key,
        uses=stats.uses,
        help_lookups=stats.helps,
        injected_example=_STATIC_QUICK_USE.get(key),
        last_seen=last_seen.isoformat() if last_seen is not None else None,
    )


def build_st_usage_memory_from_commands(
    commands: list[str] | list[tuple[str, datetime]],
    *,
    task_type: str | None = None,
    max_entries: int = 8,
) -> StUsageMemory:
    """Build quick-use memory from raw command strings plus curated fallback."""
    stats: dict[str, _CommandStats] = {}
    observed = 0
    generated_at = datetime.now(UTC)
    for item in commands:
        if isinstance(item, tuple):
            command, created_at = item
        else:
            command = item
            created_at = generated_at
        parsed = parse_st_command(command)
        if parsed is None:
            continue
        observed += 1
        bucket = stats.setdefault(parsed.key, _CommandStats())
        if parsed.is_help:
            bucket.helps += 1
        else:
            bucket.uses += 1
        if bucket.last_seen is None or created_at > bucket.last_seen:
            bucket.last_seen = created_at

    selected: list[str] = []
    selected_keys: list[str] = []
    for key in _seed_keys(task_type):
        entry = _STATIC_QUICK_USE.get(key)
        if entry and entry not in selected:
            selected.append(entry)
            selected_keys.append(key)

    ranked_keys = sorted(
        stats,
        key=lambda key: (stats[key].uses * 3 + stats[key].helps, stats[key].uses, key),
        reverse=True,
    )
    for key in ranked_keys:
        entry = _STATIC_QUICK_USE.get(key)
        if entry and entry not in selected:
            selected.append(entry)
            selected_keys.append(key)
        if len(selected) >= max_entries:
            break

    selected = selected[:max_entries]
    selected_keys = selected_keys[:max_entries]
    quick_entries = [
        _split_quick_entry(line, source="learned" if key in stats and stats[key].uses > 0 else "fallback")
        for key, line in zip(selected_keys, selected, strict=False)
    ]
    command_metrics = [_build_command_metric(key, stats[key]) for key in ranked_keys[:max_entries]]

    return StUsageMemory(
        quick=selected,
        observed=observed,
        help_count=sum(bucket.helps for bucket in stats.values()),
        generated_at=generated_at,
        quick_entries=quick_entries,
        command_metrics=command_metrics,
    )


def _extract_commands_from_rows(rows: list[tuple[Any, str | None, datetime]]) -> list[tuple[str, datetime]]:
    commands: list[tuple[str, datetime]] = []
    for tool_input, content, created_at in rows:
        command = _command_from_payload(tool_input) or _command_from_payload(content)
        if command:
            commands.append((command, created_at))
    return commands


async def _fetch_recent_st_command_rows(
    db: AsyncSession,
    *,
    project_id: str | None,
    since: datetime,
) -> list[tuple[Any, str | None, datetime]]:
    tool_input_text = SessionEvent.tool_input.cast(Text)
    content_text = SessionEvent.content.cast(Text)
    stmt = (
        select(SessionEvent.tool_input, SessionEvent.content, SessionEvent.created_at)
        .where(
            SessionEvent.event_type == SessionEventType.TOOL_USE,
            SessionEvent.created_at >= since,
            or_(
                tool_input_text.like("%st %"),
                tool_input_text.like("%\"st\"%"),
                content_text.like("%st %"),
            ),
        )
        .order_by(SessionEvent.created_at.desc())
        .limit(_QUERY_LIMIT)
    )
    if project_id:
        stmt = stmt.join(Session, Session.id == SessionEvent.session_id).where(
            Session.project_id == project_id
    )
    result = await db.execute(stmt)
    return [(tool_input, content, created_at) for tool_input, content, created_at in result.all()]


async def get_recent_st_usage_memory(
    *,
    project_id: str | None,
    task_type: str | None,
    db: AsyncSession | None = None,
) -> StUsageMemory:
    """Return cached recent st usage quick-use memory."""
    key = (project_id, task_type)
    now = datetime.now(UTC)
    cached = _CACHE.get(key)
    if cached and (now - cached[0]).total_seconds() < _CACHE_TTL_SECONDS:
        return cached[1]

    since = now - _LOOKBACK
    try:
        if db is not None:
            rows = await _fetch_recent_st_command_rows(db, project_id=project_id, since=since)
        else:
            async with async_session() as owned_db:
                rows = await _fetch_recent_st_command_rows(
                    owned_db,
                    project_id=project_id,
                    since=since,
                )
    except Exception as exc:
        logger.debug("Failed to build st usage memory: %s", exc)
        memory = build_st_usage_memory_from_commands([], task_type=task_type)
    else:
        memory = build_st_usage_memory_from_commands(
            _extract_commands_from_rows(rows),
            task_type=task_type,
        )

    _CACHE[key] = (now, memory)
    return memory
