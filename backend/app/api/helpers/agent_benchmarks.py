"""Agent benchmark dashboard helper functions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.agent_schemas import AgentBenchmarkDashboard, AgentBenchmarkRunDetail
from app.services._benchmark_dashboard import get_agent_benchmark_run_detail as _get_run_detail
from app.services.agent_benchmark_service import get_agent_benchmark_dashboard as _get_dashboard


async def get_agent_benchmark_dashboard(
    db: AsyncSession,
    agent_slug: str,
    *,
    days: int = 30,
    limit: int = 20,
    suite_id: str | None = None,
) -> AgentBenchmarkDashboard:
    """Return typed benchmark dashboard payload for one agent."""
    payload = await _get_dashboard(db, agent_slug, days=days, limit=limit, suite_id=suite_id)
    return AgentBenchmarkDashboard(**payload)


async def get_agent_benchmark_run(
    db: AsyncSession,
    agent_slug: str,
    run_id: str,
) -> AgentBenchmarkRunDetail | None:
    """Return one benchmark run with attempt-level details."""
    payload = await _get_run_detail(db, agent_slug, run_id)
    if not payload:
        return None
    return AgentBenchmarkRunDetail(**payload)
