"""Cached recall sections for heartbeat self-reflection and warm-start context."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.services.improvement_signals import collect_improvement_signal_snapshot
from app.workflows._heartbeat_data import (
    _get_recent_heartbeat_digest,
    _get_recent_idle_improvement_history,
    _render_budgeted_rows_section,
)
from app.workflows._heartbeat_redis import (
    HeartbeatRecallCache,
    get_heartbeat_recall_cache,
    set_heartbeat_recall_cache,
)

logger = logging.getLogger(__name__)

_IMPROVEMENT_SIGNAL_DAYS_BACK = 7
_IMPROVEMENT_SIGNAL_TOKEN_BUDGET = 420
_IMPROVEMENT_SIGNAL_MAX_AGENTS = 2
_IMPROVEMENT_SIGNAL_MAX_REPEATED_ISSUES = 2
_IMPROVEMENT_SIGNAL_MAX_CLUSTERS = 2
_IMPROVEMENT_SIGNAL_MAX_REFERENCES = 2


@dataclass(frozen=True)
class HeartbeatRecallSections:
    """Prefetched recall sections for one heartbeat prompt."""

    recent_heartbeat_digest: str = ""
    recent_idle_history: str = ""
    improvement_signal_digest: str = ""


def _truncate_signal_text(value: object, *, limit: int = 120) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _signal_rows(snapshot: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    for item in (snapshot.get("agent_signal_volume") or [])[:_IMPROVEMENT_SIGNAL_MAX_AGENTS]:
        if not isinstance(item, dict):
            continue
        agent_slug = str(item.get("agent_slug") or "unknown")
        friction = int(item.get("friction") or 0)
        improvement = int(item.get("improvement") or 0)
        idea = int(item.get("idea") or 0)
        praise = int(item.get("praise") or 0)
        system = int(item.get("system") or 0)
        total = friction + improvement + idea + praise + system
        if total <= 0:
            continue
        rows.append(
            f"- signals | {agent_slug} | friction={friction} improvement={improvement} "
            f"idea={idea} praise={praise} system={system}"
        )

    for item in (snapshot.get("repeated_issues") or [])[:_IMPROVEMENT_SIGNAL_MAX_REPEATED_ISSUES]:
        if not isinstance(item, dict):
            continue
        content = _truncate_signal_text(item.get("content"))
        if not content:
            continue
        rows.append(
            f"- repeat | {item.get('agent_slug') or 'unknown'} | {int(item.get('count') or 0)}x | {content}"
        )

    for item in (snapshot.get("open_regression_clusters") or [])[:_IMPROVEMENT_SIGNAL_MAX_CLUSTERS]:
        if not isinstance(item, dict):
            continue
        case_id = _truncate_signal_text(item.get("case_id"), limit=64)
        if not case_id:
            continue
        rows.append(
            f"- benchmark | {case_id} | {int(item.get('occurrence_count') or 0)}x | "
            f"{item.get('failure_category') or item.get('failure_kind') or 'unknown'}"
        )

    memory_governance = snapshot.get("memory_governance")
    if isinstance(memory_governance, dict):
        health = str(memory_governance.get("health_status") or "unknown")
        issue_count = int(memory_governance.get("issue_count") or 0)
        untargeted_refs = int(memory_governance.get("untargeted_reference_count") or 0)
        if health != "ok" or issue_count > 0 or untargeted_refs > 0:
            rows.append(
                f"- memory | health={health} issues={issue_count} untargeted_refs={untargeted_refs}"
            )

    for item in (snapshot.get("low_yield_references") or [])[:_IMPROVEMENT_SIGNAL_MAX_REFERENCES]:
        if not isinstance(item, dict):
            continue
        label = _truncate_signal_text(item.get("label"), limit=48)
        if not label:
            continue
        rows.append(
            f"- reference | {label} | selected={int(item.get('selected') or 0)} "
            f"cited={int(item.get('cited') or 0)} rate={float(item.get('citation_rate') or 0.0):.3f}"
        )
    return rows


async def _get_improvement_signal_digest(target_project_id: str | None = None) -> str:
    """Return a compact self-reflection digest for heartbeat prompt assembly."""
    try:
        snapshot = await collect_improvement_signal_snapshot(
            project_id=target_project_id,
            primary_agent_slug="persona",
            days_back=_IMPROVEMENT_SIGNAL_DAYS_BACK,
            include_team=True,
            max_agents=4,
            max_experiments=2,
            max_clusters=4,
            max_reference_items=4,
        )
    except Exception:
        logger.debug("Failed to build improvement signal digest", exc_info=True)
        return ""

    rows = _signal_rows(snapshot)
    if not rows:
        return ""
    return _render_budgeted_rows_section(
        tag="improvement_signal_digest",
        heading="Recent improvement signals",
        rows=rows,
        token_budget=_IMPROVEMENT_SIGNAL_TOKEN_BUDGET,
    )


def _from_cache(cache: HeartbeatRecallCache | None) -> HeartbeatRecallSections | None:
    if not isinstance(cache, dict):
        return None
    return HeartbeatRecallSections(
        recent_heartbeat_digest=str(cache.get("recent_heartbeat_digest") or ""),
        recent_idle_history=str(cache.get("recent_idle_history") or ""),
        improvement_signal_digest=str(cache.get("improvement_signal_digest") or ""),
    )


async def build_heartbeat_recall_sections(
    target_project_id: str | None = None,
    *,
    prefer_cache: bool = True,
) -> HeartbeatRecallSections:
    """Return warm recall sections for a heartbeat, preferring cache when fresh."""
    if prefer_cache:
        cached = _from_cache(await get_heartbeat_recall_cache(target_project_id))
        if cached is not None:
            return cached

    recent_heartbeat_digest, recent_idle_history, improvement_signal_digest = await asyncio.gather(
        _get_recent_heartbeat_digest(target_project_id),
        _get_recent_idle_improvement_history(target_project_id),
        _get_improvement_signal_digest(target_project_id),
    )
    return HeartbeatRecallSections(
        recent_heartbeat_digest=recent_heartbeat_digest,
        recent_idle_history=recent_idle_history,
        improvement_signal_digest=improvement_signal_digest,
    )


async def warm_heartbeat_recall_sections(target_project_id: str | None = None) -> HeartbeatRecallSections:
    """Refresh the prefetched recall cache after a heartbeat completes."""
    sections = await build_heartbeat_recall_sections(target_project_id, prefer_cache=False)
    await set_heartbeat_recall_cache(
        project_id=target_project_id,
        recent_heartbeat_digest=sections.recent_heartbeat_digest,
        recent_idle_history=sections.recent_idle_history,
        improvement_signal_digest=sections.improvement_signal_digest,
    )
    return sections


__all__ = [
    "HeartbeatRecallSections",
    "build_heartbeat_recall_sections",
    "warm_heartbeat_recall_sections",
]
