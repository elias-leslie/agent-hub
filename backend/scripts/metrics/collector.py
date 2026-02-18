"""Metric collection from database."""

import logging
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from metrics.models import BaselineReport, VariantMetrics, calculate_citation_rate
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def collect_metrics(days: int = 7) -> BaselineReport:
    """
    Collect injection metrics from the database.

    Args:
        days: Number of days to look back

    Returns:
        BaselineReport with aggregated metrics
    """
    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    logger.info("Collecting metrics from %s to %s", start_date.date(), end_date.date())

    async with session_factory() as session:
        # Query all metrics in date range
        query = select(MemoryInjectionMetric).where(
            MemoryInjectionMetric.created_at >= start_date,
            MemoryInjectionMetric.created_at <= end_date,
        )
        result = await session.execute(query)
        records = result.scalars().all()

    logger.info("Found %d injection records", len(records))

    # Aggregate by variant
    variant_data = _aggregate_by_variant(records)
    daily_counts = _count_by_day(records)

    # Build variant metrics
    variant_metrics = _build_variant_metrics(variant_data)

    return BaselineReport(
        start_date=start_date,
        end_date=end_date,
        total_injections=len(records),
        variant_metrics=variant_metrics,
        daily_counts=dict(daily_counts),
        query_distribution={},  # TODO: implement query categorization
    )


def _aggregate_by_variant(records) -> dict[str, dict[str, Any]]:
    """Aggregate metrics by variant."""
    variant_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "success": 0,
            "fail": 0,
            "unknown": 0,
            "retries": 0,
            "latency_sum": 0,
            "tokens_sum": 0,
            "mandates_sum": 0,
            "guardrails_sum": 0,
            "references_sum": 0,
            "loaded_sum": 0,
            "cited_sum": 0,
        }
    )

    for record in records:
        variant = record.variant or "BASELINE"
        data = variant_data[variant]

        data["total"] += 1

        if record.task_succeeded is True:
            data["success"] += 1
        elif record.task_succeeded is False:
            data["fail"] += 1
        else:
            data["unknown"] += 1

        data["retries"] += record.retries or 0
        data["latency_sum"] += record.injection_latency_ms or 0
        data["tokens_sum"] += record.total_tokens or 0
        data["mandates_sum"] += record.mandates_count or 0
        data["guardrails_sum"] += record.guardrails_count or 0
        data["references_sum"] += record.reference_count or 0

        # Count memories loaded and cited
        loaded = record.memories_loaded or []
        cited = record.memories_cited or []
        data["loaded_sum"] += len(loaded) if isinstance(loaded, list) else 0
        data["cited_sum"] += len(cited) if isinstance(cited, list) else 0

    return variant_data


def _count_by_day(records) -> dict[str, int]:
    """Count records by day."""
    daily_counts: dict[str, int] = defaultdict(int)
    for record in records:
        date_str = record.created_at.date().isoformat()
        daily_counts[date_str] += 1
    return daily_counts


def _build_variant_metrics(variant_data: dict[str, dict[str, Any]]) -> dict[str, VariantMetrics]:
    """Build VariantMetrics objects from aggregated data."""
    variant_metrics: dict[str, VariantMetrics] = {}

    for variant, data in variant_data.items():
        total = data["total"]
        if total == 0:
            continue

        variant_metrics[variant] = VariantMetrics(
            variant=variant,
            total_injections=total,
            successful_tasks=data["success"],
            failed_tasks=data["fail"],
            unknown_outcome=data["unknown"],
            total_retries=data["retries"],
            avg_latency_ms=data["latency_sum"] / total if total > 0 else 0,
            avg_tokens=int(data["tokens_sum"] / total) if total > 0 else 0,
            avg_mandates=data["mandates_sum"] / total if total > 0 else 0,
            avg_guardrails=data["guardrails_sum"] / total if total > 0 else 0,
            avg_references=data["references_sum"] / total if total > 0 else 0,
            citation_rate=calculate_citation_rate(data["loaded_sum"], data["cited_sum"]),
            total_memories_loaded=data["loaded_sum"],
            total_memories_cited=data["cited_sum"],
        )

    return variant_metrics
