"""Build compact st quick-use memory from recent tool events."""

from __future__ import annotations

import logging
import math
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

# Adaptive tool-density scoring (decay_score_by_surface): ~120d horizon with a
# 21-day half-life; per-project, falling back to global telemetry when a project
# has too few events to score on its own.
_SCORE_LOOKBACK = timedelta(days=120)
_SCORE_HALF_LIFE_DAYS = 21.0
_SCORE_FETCH_LIMIT = 5000
_SCORE_MIN_PROJECT_EVENTS = 200
_SCORE_CACHE_TTL_SECONDS = 300
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


def _build_command_metric(key: str, stats: _CommandStats) -> StUsageCommandMetric:
    last_seen = stats.last_seen
    return StUsageCommandMetric(
        command_key=key,
        uses=stats.uses,
        help_lookups=stats.helps,
        injected_example=None,
        last_seen=last_seen.isoformat() if last_seen is not None else None,
    )


def build_st_usage_memory_from_commands(
    commands: list[str] | list[tuple[str, datetime]],
    *,
    task_type: str | None = None,
    max_entries: int = 8,
) -> StUsageMemory:
    """Build telemetry-only command usage memory for the analytics dashboard.

    Tool-context injection is owned by `st tools manifest` via the @usage
    registry; this function no longer seeds curated quick-use entries.
    """
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

    ranked_keys = sorted(
        stats,
        key=lambda key: (stats[key].uses * 3 + stats[key].helps, stats[key].uses, key),
        reverse=True,
    )
    command_metrics = [_build_command_metric(key, stats[key]) for key in ranked_keys[:max_entries]]

    return StUsageMemory(
        quick=[],
        observed=observed,
        help_count=sum(bucket.helps for bucket in stats.values()),
        generated_at=generated_at,
        quick_entries=[],
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
    limit: int = _QUERY_LIMIT,
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
        .limit(limit)
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


_SCORE_CACHE: dict[str | None, tuple[datetime, dict[str, float]]] = {}


def _decay_scores_from_rows(
    rows: list[tuple[Any, str | None, datetime]],
    *,
    now: datetime,
) -> tuple[dict[str, float], int]:
    """Sum time-decayed weights per parsed st command key. Returns (weights, parsed_count)."""
    weights: dict[str, float] = {}
    parsed = 0
    for command, created_at in _extract_commands_from_rows(rows):
        spec = parse_st_command(command)
        if spec is None or spec.is_help:
            continue
        parsed += 1
        age_days = max((now - created_at).total_seconds() / 86400, 0.0)
        weight = math.pow(0.5, age_days / _SCORE_HALF_LIFE_DAYS)
        weights[spec.key] = weights.get(spec.key, 0.0) + weight
    return weights, parsed


async def decay_score_by_surface(
    project_id: str | None,
    *,
    db: AsyncSession | None = None,
    now: datetime | None = None,
) -> dict[str, float]:
    """Return 0-100 usage scores per st command key, time-decayed (21d half-life).

    Per-project over a ~120d horizon, falling back to global telemetry when the
    project has fewer than _SCORE_MIN_PROJECT_EVENTS parsed events. Keys match
    `parse_st_command` output ("db query", "pulse"); the manifest maps these to
    surfaces. Returns {} on any failure (caller falls back to full density).
    """
    now = now or datetime.now(UTC)
    cached = _SCORE_CACHE.get(project_id)
    if cached and (now - cached[0]).total_seconds() < _SCORE_CACHE_TTL_SECONDS:
        return cached[1]

    since = now - _SCORE_LOOKBACK

    async def _scores_with(session: AsyncSession) -> dict[str, float]:
        rows = await _fetch_recent_st_command_rows(
            session, project_id=project_id, since=since, limit=_SCORE_FETCH_LIMIT
        )
        weights, parsed = _decay_scores_from_rows(rows, now=now)
        if project_id and parsed < _SCORE_MIN_PROJECT_EVENTS:
            global_rows = await _fetch_recent_st_command_rows(
                session, project_id=None, since=since, limit=_SCORE_FETCH_LIMIT
            )
            weights, _ = _decay_scores_from_rows(global_rows, now=now)
        if not weights:
            return {}
        peak = max(weights.values())
        if peak <= 0:
            return {}
        return {key: round(value / peak * 100.0, 2) for key, value in weights.items()}

    try:
        if db is not None:
            scores = await _scores_with(db)
        else:
            async with async_session() as owned_db:
                scores = await _scores_with(owned_db)
    except Exception as exc:
        logger.debug("Failed to compute decay scores by surface: %s", exc)
        return {}

    _SCORE_CACHE[project_id] = (now, scores)
    return scores
