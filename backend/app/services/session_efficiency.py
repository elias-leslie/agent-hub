"""Session review on existing observations; no extra capture or causal token split."""

from __future__ import annotations

from typing import Any

from app.services.st_activity import POLICY


def efficiency_status(tool_time: dict, *, calls: int, missing: int, truncated: bool) -> str:
    goal = POLICY["session_efficiency"]
    if not tool_time["denominator_seconds"]:
        return "unmeasured"
    shares = {row["category"]: row["share"] for row in tool_time["breakdown"]}
    if (truncated or not calls or (calls - missing) / calls < goal["minimum_duration_coverage"]
            or shares["unknown"] > goal["maximum_unknown_share"]):
        return "insufficient_coverage"
    if goal["admin_share_target"] is None:
        return "goal_not_selected"
    return "within_goal" if shares["administration"] <= goal["admin_share_target"] else "above_goal"


def session_efficiency(rows: list[dict[str, Any]], *, limit: int) -> dict:
    """Rank all observed sessions before limiting, independently of token/task coverage."""
    rows.sort(key=lambda row: (
        next(part["seconds"] for part in row["tool_time"]["breakdown"] if part["category"] == "administration"),
        row["tool_time"]["denominator_seconds"], row["session_id"],
    ), reverse=True)
    return {
        "method": "session-tool-occupancy-v1",
        "goal": POLICY["session_efficiency"],
        "trial_goal": POLICY["session_efficiency_trial"],
        "sessions_total": len(rows),
        "status_counts": {status: sum(row["goal_status"] == status for row in rows)
                          for status in ("within_goal", "above_goal", "insufficient_coverage", "unmeasured", "goal_not_selected")},
        "rows": rows[:limit],
    }
