"""Data models for baseline metrics collection."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class VariantMetrics:
    """Aggregated metrics for a single variant."""

    variant: str
    total_injections: int
    successful_tasks: int
    failed_tasks: int
    unknown_outcome: int
    total_retries: int
    avg_latency_ms: float
    avg_tokens: int
    avg_mandates: float
    avg_guardrails: float
    avg_references: float
    citation_rate: float  # memories_cited / memories_loaded
    total_memories_loaded: int
    total_memories_cited: int

    @property
    def success_rate(self) -> float:
        """Calculate task success rate."""
        total_known = self.successful_tasks + self.failed_tasks
        if total_known == 0:
            return 0.0
        return self.successful_tasks / total_known

    @property
    def retry_rate(self) -> float:
        """Calculate average retries per task."""
        if self.total_injections == 0:
            return 0.0
        return self.total_retries / self.total_injections


@dataclass
class BaselineReport:
    """Complete baseline metrics report."""

    start_date: datetime
    end_date: datetime
    total_injections: int
    variant_metrics: dict[str, VariantMetrics]
    daily_counts: dict[str, int]  # date_str -> count
    query_distribution: dict[str, int]  # query category -> count


def calculate_citation_rate(loaded: int, cited: int) -> float:
    """Calculate citation rate safely."""
    if loaded == 0:
        return 0.0
    return cited / loaded
