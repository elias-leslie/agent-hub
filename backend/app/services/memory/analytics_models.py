"""Pydantic models for memory analytics."""

from pydantic import BaseModel


class TierDistribution(BaseModel):
    """Distribution of memories across injection tiers."""

    tier: str
    count: int
    percentage: float


class ScopeDistribution(BaseModel):
    """Distribution of memories across scopes (global/project)."""

    scope: str
    count: int
    percentage: float


class DailyTrend(BaseModel):
    """Daily count of memories created."""

    date: str
    count: int


class TopMemory(BaseModel):
    """High-performing memory with key metrics."""

    uuid: str
    content: str
    injection_tier: str
    utility_score: float
    loaded_count: int
    referenced_count: int
    lifecycle_score: float | None = None


class UsageTotals(BaseModel):
    """Aggregated usage totals."""

    loaded: int = 0
    cited: int = 0
    helpful: int = 0
    harmful: int = 0
    success: int = 0


class VariantMetrics(BaseModel):
    """Aggregated metrics for a single variant."""

    variant: str
    injection_count: int
    success_count: int
    fail_count: int
    unknown_count: int
    success_rate: float
    citation_rate: float
    avg_latency_ms: float
    avg_tokens: float


class TimePeriodMetrics(BaseModel):
    """Metrics aggregated by time period."""

    period: str
    injection_count: int
    avg_success_rate: float
    avg_citation_rate: float


class OutcomeSummary(BaseModel):
    """Outcome coverage and success summary for a recent activity window."""

    success_count: int
    fail_count: int
    unknown_count: int
    known_count: int
    coverage_rate: float
    success_rate: float


class InjectionMetricsSummary(BaseModel):
    """Time-windowed injection activity summary."""

    total_injections: int
    period_start: str
    period_end: str
    period_granularity: str
    by_variant: list[VariantMetrics]
    by_period: list[TimePeriodMetrics]
    overall_success_rate: float
    overall_citation_rate: float
    outcomes: OutcomeSummary


class MemoryAnalyticsState(BaseModel):
    """Current memory system state derived from memory records."""

    total_episodes: int
    tier_distribution: list[TierDistribution]
    scope_distribution: list[ScopeDistribution]
    usage_totals: UsageTotals
    avg_utility_score: float
    avg_lifecycle_score: float = 0.0
    lifecycle_by_tier: dict[str, float] = {}
    top_memories: list[TopMemory]


class MemoryAnalyticsActivity(BaseModel):
    """Recent activity derived from event/injection tables."""

    lookback: str
    usage_totals: UsageTotals
    injection_metrics: InjectionMetricsSummary
    tier_changes: dict[str, object]


class MemoryAnalyticsDashboard(BaseModel):
    """Full dashboard payload with explicit state and activity sections."""

    state: MemoryAnalyticsState
    activity: MemoryAnalyticsActivity
