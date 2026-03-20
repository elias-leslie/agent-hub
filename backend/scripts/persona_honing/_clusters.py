"""Failure cluster analysis for the persona honing loop."""
from __future__ import annotations

from typing import Any


def _cluster_key(cluster: dict[str, Any]) -> tuple[str, str]:
    return (str(cluster.get("case_id", "")), str(cluster.get("failure_detail", "")))


def _group_failures(attempts: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt in attempts:
        if attempt.passed:
            continue
        key = (attempt.case_id, attempt.failure_detail or "failed")
        bucket = grouped.setdefault(key, {
            "case_id": attempt.case_id,
            "failure_detail": attempt.failure_detail or "failed",
            "count": 0,
            "models": set(),
            "avg_score_total": 0.0,
        })
        bucket["count"] += 1
        bucket["models"].add(attempt.model_id)
        bucket["avg_score_total"] += attempt.composite_score

    ranked = [
        {
            "case_id": b["case_id"],
            "failure_detail": b["failure_detail"],
            "count": b["count"],
            "models": sorted(b["models"]),
            "avg_score": round(b["avg_score_total"] / b["count"], 1),
        }
        for b in grouped.values()
    ]
    ranked.sort(key=lambda item: (-item["count"], item["avg_score"], item["case_id"]))
    return ranked


def _diff_failure_clusters(
    previous: list[dict[str, Any]] | None,
    current: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (persistent, new, resolved) clusters across iterations."""
    previous_map = {_cluster_key(c): c for c in (previous or [])}
    current_map = {_cluster_key(c): c for c in current}
    persistent = [current_map[k] for k in current_map if k in previous_map]
    new = [current_map[k] for k in current_map if k not in previous_map]
    resolved = [previous_map[k] for k in previous_map if k not in current_map]
    return persistent, new, resolved


def _render_cluster_block(clusters: list[dict[str, Any]], label: str) -> str:
    if not clusters:
        return f"{label}:\n- none"
    lines = [f"{label}:"]
    for c in clusters:
        models = ", ".join(c.get("models", []))
        lines.append(
            f"- case={c['case_id']} count={c['count']} avg_score={c['avg_score']} "
            f"models={models} detail={c['failure_detail']}"
        )
    return "\n".join(lines)
