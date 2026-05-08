"""Heartbeat section builders for agent roster, feedback, and persona tools.

These sections have no IO dependencies patched by tests, so they can live
here independently from the main orchestrator module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _get_persona_tool_summary(provider: str | None = None) -> tuple[int, str]:
    """Return the default non-core persona tool summary."""
    del provider
    return 0, "none; shell-first core tools only"


async def _get_agent_roster_summary() -> str:
    """Build a compact <agent_roster> XML block listing active agent slugs."""
    try:
        from app.db import async_session
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        async with async_session() as db:
            agents = await agent_service.list_agents(db, active_only=True)

        if not agents:
            return ""

        coding_agents = sorted(a.slug for a in agents if a.is_coding_agent)
        general_count = sum(1 for a in agents if not a.is_coding_agent)
        lines = [
            f"Active agents: {len(agents)}; coding={len(coding_agents)}; general={general_count}"
        ]
        if coding_agents:
            lines.append(f"Coding ({len(coding_agents)}): {', '.join(coding_agents)}")
        if general_count:
            lines.append("General roster: inspect with `st agents list` for exact dispatch fit.")
        body = "\n".join(lines)
        logger.info("Agent roster summary: %d agents", len(agents))
        return f"\n<agent_roster>\n{body}\n</agent_roster>"
    except Exception:
        logger.debug("Failed to fetch agent roster for heartbeat prompt", exc_info=True)
        return ""


async def _get_feedback_summary_section() -> str:
    """Build a <feedback_summary> XML block with open feedback stats and top items."""
    try:
        from app.db import async_session
        from app.services.feedback_storage import get_feedback_summary

        async with async_session() as db:
            summary = await get_feedback_summary(db, days=30)

        top_items = summary.get("top_unresolved", [])
        if not top_items:
            return ""

        type_counts = _count_feedback_by_type(summary)
        unresolved_count = sum(type_counts.values())
        if unresolved_count == 0:
            return ""

        lines = _build_feedback_lines(summary, type_counts, unresolved_count, top_items)
        body = "\n".join(lines)
        logger.info("Feedback summary: %d unresolved items", unresolved_count)
        return f"\n<feedback_summary>\n{body}\n</feedback_summary>"
    except Exception:
        logger.debug("Failed to fetch feedback summary for heartbeat", exc_info=True)
        return ""


def _count_feedback_by_type(summary: dict[str, object]) -> dict[str, int]:
    """Aggregate open/acknowledged feedback counts by type."""
    type_counts: dict[str, int] = {}
    for row in summary.get("counts_by_type_status", []):  # type: ignore[union-attr]
        if row.get("status") in {"open", "acknowledged"}:
            ft = row.get("feedback_type", "unknown")
            type_counts[ft] = type_counts.get(ft, 0) + row.get("count", 0)
    return type_counts


def _build_feedback_lines(
    summary: dict[str, object],
    type_counts: dict[str, int],
    unresolved_count: int,
    top_items: list[object],
) -> list[str]:
    """Build display lines for the feedback summary section."""
    lines: list[str] = [
        f"Unresolved items: {unresolved_count} (of {summary.get('total_items', 0)} total, last 30d)"
    ]
    if type_counts:
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(type_counts.items()))
        lines.append(f"By type: {breakdown}")
    hot = [r for r in summary.get("by_component", []) if int(r.get("open_count", 0) or 0) > 0][:3]  # type: ignore[union-attr]
    if hot:
        hotspots = ", ".join(
            f"{r['component_id']} open={r['open_count']} votes={r['total_votes'] or 0}"
            for r in hot
        )
        lines.append(f"Hotspots: {hotspots}")
    lines += ["", f"{'ID':>8}  {'Type':<11}  {'Component':<20}  {'Votes':>5}  Title", "-" * 78]
    for item in top_items[:5]:
        short_id = str(item.id)[:8]  # type: ignore[union-attr]
        lines.append(
            f"{short_id:>8}  {item.feedback_type:<11}  "  # type: ignore[union-attr]
            f"{item.component_id:<20}  {item.vote_count:>5}  "  # type: ignore[union-attr]
            f"{(item.title or '')[:40]}"  # type: ignore[union-attr]
        )
    return lines
