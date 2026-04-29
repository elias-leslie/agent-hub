"""Pydantic models for memory analytics."""

from pydantic import BaseModel, Field


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


class MemoryUtilizationMetrics(BaseModel):
    """Recent evidence that agents are using injected memory effectively."""

    injection_sessions: int
    citation_sessions: int
    lookup_sessions: int
    lookup_after_injection_sessions: int
    memory_search_calls: int
    memory_get_calls: int
    assistant_message_count: int
    assistant_messages_with_memory_citations: int
    citation_session_rate: float
    lookup_session_rate: float
    expansion_session_rate: float
    assistant_citation_rate: float
    sessions_with_selected_references: int
    sessions_with_cited_selected_references: int
    selected_reference_count: int
    selected_reference_cited_count: int
    selected_reference_citation_rate: float
    selected_reference_session_rate: float
    memory_inject_event_count: int
    memory_inject_events_with_debug: int
    memory_debug_coverage_rate: float


class StUsageQuickEntryModel(BaseModel):
    """One st quick-use example injected into tool capabilities."""

    command: str
    description: str
    source: str


class StUsageCommandMetricModel(BaseModel):
    """Observed usage metrics for a single st command key."""

    command_key: str
    uses: int
    help_lookups: int
    injected_example: str | None = None
    last_seen: str | None = None


class StUsageSummary(BaseModel):
    """Recent st command usage and injected quick-use payload."""

    observed_commands: int = 0
    help_lookups: int = 0
    help_rate: float = 0.0
    quick_entry_count: int = 0
    quick_entries: list[StUsageQuickEntryModel] = Field(default_factory=list)
    command_metrics: list[StUsageCommandMetricModel] = Field(default_factory=list)
    payload_preview: str = ""
    cache_ttl_seconds: int = 60
    lookback: str = "14d"
    generated_at: str | None = None


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
    utilization: MemoryUtilizationMetrics
    st_usage: StUsageSummary = Field(default_factory=StUsageSummary)
    tier_changes: dict[str, object]


class MemoryAnalyticsDashboard(BaseModel):
    """Full dashboard payload with explicit state and activity sections."""

    state: MemoryAnalyticsState
    activity: MemoryAnalyticsActivity
