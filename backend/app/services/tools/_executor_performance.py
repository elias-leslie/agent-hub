"""Agent performance tracking tool implementations for DirectToolExecutor."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

VALID_FEEDBACK_TYPES = {"friction", "improvement", "idea", "praise"}
VALID_OUTCOMES = {"success", "partial", "failure", "timeout", "fallback"}


async def log_agent_performance(
    agent_slug: str,
    model_id: str,
    feedback_type: str,
    content: str,
    outcome: str = "success",
    task_type: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_calls_count: int | None = None,
    turns: int | None = None,
    logged_by: str = "persona",
) -> str:
    """Log a performance observation for an agent/model combination."""
    if feedback_type not in VALID_FEEDBACK_TYPES:
        return (
            f"Error: Invalid feedback_type '{feedback_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_FEEDBACK_TYPES))}"
        )

    if outcome not in VALID_OUTCOMES:
        return (
            f"Error: Invalid outcome '{outcome}'. "
            f"Must be one of: {', '.join(sorted(VALID_OUTCOMES))}"
        )

    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.agent_performance_log import AgentPerformanceLog

        async with async_session() as db:
            # 24h dedup: skip only exact duplicate observations, not distinct issues.
            cutoff = datetime.now(UTC) - timedelta(hours=24)
            existing = await db.execute(
                select(AgentPerformanceLog.id)
                .where(
                    AgentPerformanceLog.agent_slug == agent_slug,
                    AgentPerformanceLog.model_id == model_id,
                    AgentPerformanceLog.feedback_type == feedback_type,
                    AgentPerformanceLog.content == content,
                    AgentPerformanceLog.created_at > cutoff,
                )
                .limit(1)
            )
            if existing.scalar_one_or_none() is not None:
                return (
                    f"Skipped: {feedback_type} for {agent_slug} ({model_id}) "
                    f"already logged within 24h"
                )

            log = AgentPerformanceLog(
                agent_slug=agent_slug,
                model_id=model_id,
                task_type=task_type,
                project_id=project_id,
                outcome=outcome,
                feedback_type=feedback_type,
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls_count=tool_calls_count,
                turns=turns,
                content=content,
                session_id=session_id,
                logged_by=logged_by,
            )

            db.add(log)
            await db.commit()
            await db.refresh(log)

        return (
            f"Performance logged: {feedback_type} for {agent_slug} ({model_id}) "
            f"— outcome={outcome}, id={log.id}"
        )
    except Exception as e:
        logger.exception("log_agent_performance failed")
        return f"Error logging performance: {e}"


async def review_agent_performance(
    agent_slug: str | None = None,
    model_id: str | None = None,
    feedback_type: str | None = None,
    days_back: int = 30,
    limit: int = 50,
) -> str:
    """Review performance history for agents and models."""
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import func, select

        from app.db import async_session
        from app.models.agent_performance_log import AgentPerformanceLog

        cutoff = datetime.now(UTC) - timedelta(days=days_back)

        async with async_session() as db:
            query = (
                select(AgentPerformanceLog)
                .where(AgentPerformanceLog.created_at >= cutoff)
                .order_by(AgentPerformanceLog.created_at.desc())
                .limit(limit)
            )
            if agent_slug:
                query = query.where(AgentPerformanceLog.agent_slug == agent_slug)
            if model_id:
                query = query.where(AgentPerformanceLog.model_id == model_id)
            if feedback_type:
                query = query.where(AgentPerformanceLog.feedback_type == feedback_type)

            result = await db.execute(query)
            entries = result.scalars().all()

            summary_query = (
                select(
                    AgentPerformanceLog.agent_slug,
                    AgentPerformanceLog.model_id,
                    AgentPerformanceLog.feedback_type,
                    func.count().label("count"),
                )
                .where(AgentPerformanceLog.created_at >= cutoff)
                .group_by(
                    AgentPerformanceLog.agent_slug,
                    AgentPerformanceLog.model_id,
                    AgentPerformanceLog.feedback_type,
                )
            )
            if agent_slug:
                summary_query = summary_query.where(AgentPerformanceLog.agent_slug == agent_slug)
            if model_id:
                summary_query = summary_query.where(AgentPerformanceLog.model_id == model_id)

            summary_result = await db.execute(summary_query)
            summary_rows = summary_result.all()

        if not entries:
            filters = []
            if agent_slug:
                filters.append(f"agent={agent_slug}")
            if model_id:
                filters.append(f"model={model_id}")
            if feedback_type:
                filters.append(f"type={feedback_type}")
            filter_str = f" ({', '.join(filters)})" if filters else ""
            return f"(No performance logs in the last {days_back} days{filter_str})"

        lines = ["# Performance Summary\n"]

        if summary_rows:
            lines.append("## Aggregated Counts")
            for row in summary_rows:
                lines.append(f"  {row.agent_slug} x {row.model_id} [{row.feedback_type}]: {row.count}")
            lines.append("")

        lines.append(f"## Recent Entries (last {days_back} days)\n")
        for e in entries:
            date = e.created_at.strftime("%Y-%m-%d %H:%M") if e.created_at else "?"
            metrics = []
            if e.duration_ms:
                metrics.append(f"{e.duration_ms}ms")
            if e.turns:
                metrics.append(f"{e.turns} turns")
            if e.tool_calls_count:
                metrics.append(f"{e.tool_calls_count} tools")
            metric_str = f" ({', '.join(metrics)})" if metrics else ""
            lines.append(
                f"### {date} [{e.feedback_type}] {e.agent_slug} x {e.model_id}\n"
                f"Outcome: {e.outcome}{metric_str}\n"
                f"{e.content}\n"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.exception("review_agent_performance failed")
        return f"Error reviewing performance: {e}"


async def review_improvement_signals(
    project_id: str | None = None,
    primary_agent_slug: str = "persona",
    days_back: int = 7,
    include_team: bool = True,
    max_agents: int = 4,
    max_references: int = 6,
) -> str:
    """Review combined performance, benchmark, and memory signals."""
    try:
        from app.services.improvement_signals import build_improvement_signal_digest

        return await build_improvement_signal_digest(
            project_id=project_id,
            primary_agent_slug=primary_agent_slug,
            days_back=days_back,
            include_team=include_team,
            max_agents=max_agents,
            max_reference_items=max_references,
        )
    except Exception as e:
        logger.exception("review_improvement_signals failed")
        return f"Error reviewing improvement signals: {e}"
