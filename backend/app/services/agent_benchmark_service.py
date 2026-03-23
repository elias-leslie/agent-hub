"""Persistence and dashboard queries for agent benchmark tracking.

Split into sub-modules for maintainability:
  - _benchmark_config.py: config snapshot capture and fingerprinting
  - _benchmark_persistence.py: persist runs, regression clusters
  - _benchmark_dashboard.py: dashboard queries, formatting, experiment stats
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentBenchmarkExperiment, AgentBenchmarkRun

# ---------------------------------------------------------------------------
# Re-exports (preserve public API for all importers)
# ---------------------------------------------------------------------------
from ._benchmark_config import (
    capture_benchmark_config_snapshot,  # noqa: F401
    memory_state_descriptor,  # noqa: F401
)
from ._benchmark_dashboard import (
    benchmark_signal_run_clause,
    get_agent_benchmark_dashboard,  # noqa: F401
    summarize_benchmark_experiment,
)
from ._benchmark_persistence import persist_benchmark_payload  # noqa: F401
from ._benchmark_persistence import (  # noqa: F401
    should_update_regression_clusters as _should_update_regression_clusters,
)


async def get_benchmark_experiment_summary_by_key(
    db: AsyncSession,
    experiment_key: str,
) -> dict[str, Any] | None:
    experiment = await db.scalar(
        select(AgentBenchmarkExperiment).where(
            AgentBenchmarkExperiment.experiment_key == experiment_key
        )
    )
    if experiment is None:
        return None

    runs = (
        await db.execute(
            select(AgentBenchmarkRun)
            .where(
                AgentBenchmarkRun.experiment_id == experiment.id,
                AgentBenchmarkRun.completed_at.is_not(None),
                benchmark_signal_run_clause(AgentBenchmarkRun),
            )
            .order_by(AgentBenchmarkRun.completed_at.desc())
        )
    ).scalars().all()
    return summarize_benchmark_experiment(experiment, list(runs))
