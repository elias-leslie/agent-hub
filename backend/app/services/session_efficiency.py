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


def duration_split(seconds: dict[str, float], *, calls: int, missing: int, truncated: bool) -> dict:
    """Weighted occupancy shares; missing duration has unknown size, including at zero."""
    admin = seconds.get("administration", 0) + seconds.get("necessary_support", 0)
    unknown = seconds.get("unknown", 0) + seconds.get("mixed", 0)
    other = seconds.get("substantive", 0) + unknown
    denominator = admin + other
    return {
        "admin_seconds": round(admin, 3), "other_seconds": round(other, 3),
        "denominator_seconds": round(denominator, 3),
        "admin_share": admin / denominator if denominator else None,
        "other_share": other / denominator if denominator else None,
        "unknown_seconds": round(unknown, 3),
        "unknown_share": unknown / denominator if denominator else None,
        "tools_sampled": calls, "tools_missing_duration": missing,
        "duration_coverage": (calls - missing) / calls if calls else None,
        "events_truncated": truncated,
    }
