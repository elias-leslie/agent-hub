"""Agent benchmark dashboard helper functions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.agent_schemas import AgentBenchmarkDashboard
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
