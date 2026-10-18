"""Spend patterns: where model calls cost more than they should, or can't be priced.

Counts only (no prompts or titles). Each section is computed independently, so one
failing query marks that section unavailable instead of hiding the others.
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

HIGH_EFFORTS = ("xhigh", "max")
REPEAT_WINDOW_SECONDS = 600
SPIKE_RATIO = 2.0
PRIOR_WINDOWS = 4
TOP = 8


async def _unpriced(db: AsyncSession, since: datetime) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT model, count(*) AS calls,
               sum(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens) AS tokens,
               sum(cost_usd) AS cash, sum(coalesce(api_equiv_usd, 0)) AS value,
               sum(coalesce(credits_used, 0)) AS credits
        FROM cost_logs WHERE created_at >= :since GROUP BY model
    """), {"since": since})).mappings().all()
    unpriced = [
        {"model": r["model"], "calls": int(r["calls"]), "tokens": int(r["tokens"] or 0)}
        for r in rows
        if int(r["tokens"] or 0) > 0 and not r["cash"] and not r["value"] and not r["credits"]
    ]
    unpriced.sort(key=lambda u: -u["tokens"])
    return {
        "calls": sum(int(r["calls"]) for r in rows),
        "unpriced_calls": sum(u["calls"] for u in unpriced),
        "models": unpriced[:TOP],
    }


async def _effort(db: AsyncSession, since: datetime) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT s.provider_metadata -> 'model_evidence' ->> 'requested_reasoning_effort' AS effort,
               count(DISTINCT s.id) AS sessions,
               coalesce(sum(c.input_tokens + c.output_tokens + c.cache_read_tokens + c.cache_write_tokens), 0) AS tokens
        FROM sessions s LEFT JOIN cost_logs c ON c.session_id = s.id
        WHERE s.created_at >= :since
          AND s.provider_metadata -> 'model_evidence' ->> 'requested_reasoning_effort' IS NOT NULL
        GROUP BY 1
    """), {"since": since})).mappings().all()
    levels = sorted(
        ({"effort": r["effort"], "sessions": int(r["sessions"]), "tokens": int(r["tokens"])} for r in rows),
        key=lambda level: -level["sessions"],
    )
    total_sessions = sum(level["sessions"] for level in levels)
    total_tokens = sum(level["tokens"] for level in levels)
    high = [level for level in levels if level["effort"] in HIGH_EFFORTS]
    return {
        "levels": levels,
        "sessions_with_effort": total_sessions,
        "high_session_share": round(sum(h["sessions"] for h in high) / total_sessions, 3) if total_sessions else None,
        "high_token_share": round(sum(h["tokens"] for h in high) / total_tokens, 3) if total_tokens else None,
    }


async def _model_names(db: AsyncSession, since: datetime) -> dict[str, Any]:
    from app.models import ModelAlias

    aliases = {a.lower() for a in (await db.execute(select(ModelAlias.alias))).scalars().all()}
    rows = (await db.execute(text("""
        SELECT coalesce(model, '') AS model, count(*) AS sessions
        FROM sessions WHERE created_at >= :since GROUP BY 1
    """), {"since": since})).mappings().all()
    unnamed: list[dict[str, Any]] = []
    total = 0
    for r in rows:
        name = str(r["model"])
        base = name.rsplit("/", 1)[-1].strip().lower()
        if not base or base == "unknown" or base.startswith("<"):
            kind = "no model name"
        elif base in aliases:
            kind = "alias, not a model"
        else:
            continue
        total += int(r["sessions"])
        unnamed.append({"model": name or "(empty)", "kind": kind, "sessions": int(r["sessions"])})
    unnamed.sort(key=lambda u: -u["sessions"])
    return {"sessions": total, "names": unnamed[:TOP]}


async def _empty_sessions(db: AsyncSession, since: datetime) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT coalesce(s.project_id, '?') AS project, coalesce(s.request_source, s.session_type::text) AS source,
               count(*) AS sessions
        FROM sessions s
        WHERE s.created_at >= :since AND s.status IN ('completed', 'failed')
          AND s.session_type::text <> 'image_generation'
          AND NOT EXISTS (SELECT 1 FROM session_events e WHERE e.session_id = s.id)
          AND NOT EXISTS (SELECT 1 FROM cost_logs c WHERE c.session_id = s.id)
        GROUP BY 1, 2 ORDER BY 3 DESC
    """), {"since": since})).mappings().all()
    return {
        "sessions": sum(int(r["sessions"]) for r in rows),
        "by_source": [dict(project=r["project"], source=r["source"], sessions=int(r["sessions"])) for r in rows[:TOP]],
    }


async def _repeated_calls(db: AsyncSession, since: datetime) -> dict[str, Any]:
    rows = (await db.execute(text("""
        WITH calls AS (
            SELECT coalesce(s.project_id, '?') AS project, coalesce(s.request_source, s.session_type::text) AS source,
                   c.model, c.input_tokens, c.created_at,
                   lag(c.created_at) OVER (
                       PARTITION BY s.project_id, s.request_source, c.model, c.input_tokens ORDER BY c.created_at
                   ) AS previous_at
            FROM cost_logs c JOIN sessions s ON s.id = c.session_id
            WHERE c.created_at >= :since AND c.input_tokens > 0
        )
        SELECT project, source, count(*) AS repeats FROM calls
        WHERE previous_at IS NOT NULL AND created_at - previous_at < make_interval(secs => :window)
        GROUP BY 1, 2 ORDER BY 3 DESC
    """), {"since": since, "window": REPEAT_WINDOW_SECONDS})).mappings().all()
    return {
        "window_minutes": REPEAT_WINDOW_SECONDS // 60,
        "repeats": sum(int(r["repeats"]) for r in rows),
        "by_caller": [dict(project=r["project"], source=r["source"], repeats=int(r["repeats"])) for r in rows[:TOP]],
    }


async def _gated_automations(db: AsyncSession) -> dict[str, Any]:
    from app.models import AutomationDefinition, AutomationProfile
    from app.services import automations as service

    profiles = (await db.execute(
        select(AutomationProfile).where(AutomationProfile.enabled.is_(True))
    )).scalars().all()
    gated: list[dict[str, Any]] = []
    for row in profiles:
        definition = await db.get(AutomationDefinition, (row.workflow_key, row.definition_version))
        if definition is None:
            gated.append({"label": row.label, "project": row.project_id, "reasons": ["definition_missing"]})
            continue
        policy = await service.get_policy(db, row.project_id)
        reasons = service.effective_gate_reasons(
            profile_enabled=row.enabled, policy_enabled=policy.enabled,
            owner_gate_reasons=await service.live_owner_gate_reasons(db, row),
            manual=False, manual_when_disabled=definition.manual_when_disabled,
        )
        if reasons:
            gated.append({"label": row.label, "project": row.project_id, "reasons": reasons})
    return {"enabled": len(profiles), "gated": gated}


async def _weekly_spike(db: AsyncSession, now: datetime, days: int) -> dict[str, Any]:
    windows: list[dict[str, float]] = []
    for index in range(PRIOR_WINDOWS + 1):
        end = now - timedelta(days=days * index)
        row = (await db.execute(text("""
            SELECT coalesce(sum(cost_usd), 0) AS cash,
                   coalesce(sum(input_tokens + output_tokens + cache_read_tokens + cache_write_tokens), 0) AS tokens
            FROM cost_logs WHERE created_at >= :start AND created_at < :end
        """), {"start": end - timedelta(days=days), "end": end})).mappings().one()
        windows.append({"cash": float(row["cash"]), "tokens": float(row["tokens"])})
    current, prior = windows[0], windows[1:]
    measure = "cash" if any(w["cash"] for w in windows) else "tokens"
    usual = statistics.median(w[measure] for w in prior)
    ratio = round(current[measure] / usual, 2) if usual else None
    return {
        "measure": measure,
        "current": current[measure],
        "usual": usual,
        "ratio": ratio,
        "spike": ratio is not None and ratio > SPIKE_RATIO,
    }


async def build_spend_patterns(db: AsyncSession, days: int = 7) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    sections = {
        "unpriced": lambda: _unpriced(db, since),
        "effort": lambda: _effort(db, since),
        "model_names": lambda: _model_names(db, since),
        "empty_sessions": lambda: _empty_sessions(db, since),
        "repeated_calls": lambda: _repeated_calls(db, since),
        "gated_automations": lambda: _gated_automations(db),
        "weekly_spike": lambda: _weekly_spike(db, now, days),
    }
    out: dict[str, Any] = {"window_days": days, "generated_at": now.isoformat(), "unavailable": []}
    for name, compute in sections.items():
        try:
            out[name] = await compute()
        except Exception:
            logger.exception("spend pattern %s failed", name)
            await db.rollback()
            out[name] = None
            out["unavailable"].append(name)
    return out
