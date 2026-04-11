"""Admin-facing hotspot analytics for repeated work and token waste."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostLog, Session, SessionEvent, SessionEventType
from app.services._session_metadata_helpers import (
    session_attribution,
    session_metadata,
    source_client,
)
from app.services.session_live_activity import build_live_activity_response


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _preview_line(content: str | None) -> str | None:
    text = _coerce_text(content)
    if not text:
        return None
    return text.splitlines()[0][:140]


def _rate_limit_reason(session: Session) -> str | None:
    metadata = session_metadata(session)
    for key in ("fallback_reason", "execution_error"):
        value = _coerce_text(metadata.get(key))
        if value and any(token in value.lower() for token in ("ratelimit", "rate limit", "429")):
            return value
    return None


def _workload_identity(session: Session, preview: str | None) -> tuple[str, str, str | None]:
    project = session.project_id
    agent = session.agent_slug or "-"
    if session.external_id:
        label = preview or session.external_id
        return (
            f"{project}:{agent}:external:{session.external_id}",
            label,
            session.external_id,
        )
    if session.request_source:
        label = preview or session.request_source
        return (
            f"{project}:{agent}:source:{session.request_source}",
            label,
            session.request_source,
        )
    fallback = preview or session.model or "unknown"
    return (
        f"{project}:{agent}:prompt:{fallback}",
        fallback,
        None,
    )


async def build_session_hotspot_snapshot(
    db: AsyncSession,
    *,
    hours: int = 24,
    limit: int = 5,
) -> dict[str, Any]:
    """Return hotspot analytics for recent sessions and current active ghosts."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=hours)

    recent_sessions = (
        await db.execute(
            select(Session).where(Session.created_at >= cutoff).order_by(Session.created_at.desc())
        )
    ).scalars().all()

    session_ids = [session.id for session in recent_sessions]
    cost_by_session: dict[str, dict[str, float | int]] = {}
    first_user_message: dict[str, str | None] = {}

    if session_ids:
        cost_rows = (
            await db.execute(
                select(
                    CostLog.session_id,
                    func.coalesce(func.sum(CostLog.input_tokens), 0).label("input_tokens"),
                    func.coalesce(func.sum(CostLog.output_tokens), 0).label("output_tokens"),
                    func.coalesce(func.sum(CostLog.cost_usd), 0.0).label("cost_usd"),
                )
                .where(CostLog.session_id.in_(session_ids))
                .group_by(CostLog.session_id)
            )
        ).all()
        cost_by_session = {
            str(row.session_id): {
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
                "cost_usd": float(row.cost_usd or 0.0),
            }
            for row in cost_rows
        }

        message_rows = (
            await db.execute(
                select(
                    SessionEvent.session_id,
                    SessionEvent.content,
                    SessionEvent.turn,
                    SessionEvent.sequence,
                )
                .where(
                    SessionEvent.session_id.in_(session_ids),
                    SessionEvent.event_type == SessionEventType.USER_MESSAGE,
                )
                .order_by(SessionEvent.session_id.asc(), SessionEvent.turn.asc(), SessionEvent.sequence.asc())
            )
        ).all()
        for row in message_rows:
            session_id = str(row.session_id)
            if session_id not in first_user_message:
                first_user_message[session_id] = _coerce_text(row.content)

    totals = {
        "sessions": len(recent_sessions),
        "input_tokens": 0,
        "output_tokens": 0,
        "total_cost_usd": 0.0,
        "active_sessions": 0,
        "rate_limit_fallback_sessions": 0,
        "missing_attribution_sessions": 0,
    }
    attribution_buckets: dict[str, dict[str, Any]] = {}
    repeated_buckets: dict[str, dict[str, Any]] = {}
    low_yield_items: list[dict[str, Any]] = []

    for session in recent_sessions:
        costs = cost_by_session.get(session.id, {})
        input_tokens = int(costs.get("input_tokens", 0) or 0)
        output_tokens = int(costs.get("output_tokens", 0) or 0)
        cost_usd = float(costs.get("cost_usd", 0.0) or 0.0)
        preview = _preview_line(first_user_message.get(session.id))
        attribution = session_attribution(session)

        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["total_cost_usd"] += cost_usd
        if session.status == "active":
            totals["active_sessions"] += 1
        if _rate_limit_reason(session):
            totals["rate_limit_fallback_sessions"] += 1
        if not session.request_source and not source_client(session):
            totals["missing_attribution_sessions"] += 1

        kind = str(attribution["attribution_kind"] or "unknown")
        bucket = attribution_buckets.setdefault(
            kind,
            {
                "kind": kind,
                "label": attribution["attribution_label"] or kind.title(),
                "sessions": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_cost_usd": 0.0,
            },
        )
        bucket["sessions"] += 1
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["total_cost_usd"] += cost_usd

        workload_key, workload_label, workload_detail = _workload_identity(session, preview)
        repeated_bucket = repeated_buckets.setdefault(
            workload_key,
            {
                "workload_key": workload_key,
                "label": workload_label,
                "detail": workload_detail,
                "project_id": session.project_id,
                "agent_slug": session.agent_slug,
                "sessions": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_cost_usd": 0.0,
            },
        )
        repeated_bucket["sessions"] += 1
        repeated_bucket["input_tokens"] += input_tokens
        repeated_bucket["output_tokens"] += output_tokens
        repeated_bucket["total_cost_usd"] += cost_usd

        if input_tokens >= 5000 and output_tokens <= 500:
            low_yield_items.append(
                {
                    "session_id": session.id,
                    "project_id": session.project_id,
                    "agent_slug": session.agent_slug,
                    "status": session.status,
                    "model": session.model,
                    "label": preview or session.external_id or session.request_source or session.id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_cost_usd": cost_usd,
                    "attribution_label": attribution["attribution_label"],
                    "efficiency_ratio": round(input_tokens / max(output_tokens, 1), 2),
                }
            )

    active_sessions = (
        await db.execute(select(Session).where(Session.status == "active").order_by(Session.updated_at.desc()))
    ).scalars().all()
    zero_event_active: list[dict[str, Any]] = []
    for session in active_sessions:
        activity = build_live_activity_response(session)
        if not activity:
            continue
        if activity.get("last_event_type"):
            continue
        if int(activity.get("tool_calls_count") or 0) != 0:
            continue
        zero_event_active.append(
            {
                "session_id": session.id,
                "project_id": session.project_id,
                "agent_slug": session.agent_slug,
                "request_source": session.request_source,
                "quiet_for_seconds": int(activity.get("quiet_for_seconds") or 0),
                "lifecycle_state": activity.get("lifecycle_state"),
            }
        )

    repeated_workloads = [
        bucket
        for bucket in repeated_buckets.values()
        if int(bucket["sessions"]) > 1
    ]
    repeated_workloads.sort(
        key=lambda item: (
            float(item["total_cost_usd"]),
            int(item["input_tokens"]),
            int(item["sessions"]),
        ),
        reverse=True,
    )

    low_yield_items.sort(
        key=lambda item: (
            float(item["efficiency_ratio"]),
            float(item["total_cost_usd"]),
            int(item["input_tokens"]),
        ),
        reverse=True,
    )
    zero_event_active.sort(key=lambda item: int(item["quiet_for_seconds"]), reverse=True)

    attribution_rows = sorted(
        attribution_buckets.values(),
        key=lambda item: (float(item["total_cost_usd"]), int(item["input_tokens"])),
        reverse=True,
    )

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "totals": {
            **totals,
            "total_cost_usd": round(float(totals["total_cost_usd"]), 4),
            "zero_event_active_sessions": len(zero_event_active),
        },
        "attribution_breakdown": [
            {**row, "total_cost_usd": round(float(row["total_cost_usd"]), 4)}
            for row in attribution_rows[:limit]
        ],
        "repeated_workloads": [
            {**row, "total_cost_usd": round(float(row["total_cost_usd"]), 4)}
            for row in repeated_workloads[:limit]
        ],
        "low_yield_sessions": [
            {**row, "total_cost_usd": round(float(row["total_cost_usd"]), 4)}
            for row in low_yield_items[:limit]
        ],
        "zero_event_active_sessions": zero_event_active[:limit],
    }
