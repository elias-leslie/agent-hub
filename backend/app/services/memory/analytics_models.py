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


class MemoryAnalytics(BaseModel):
    """Aggregate analytics for memory usage and performance."""

    total_episodes: int
    tier_distribution: list[TierDistribution]
    scope_distribution: list[ScopeDistribution]
    total_loaded: int
    total_cited: int
    total_helpful: int
    total_harmful: int
    total_success: int
    citation_rate: float
    success_rate: float
    daily_trend: list[DailyTrend]
    avg_utility_score: float
    avg_lifecycle_score: float = 0.0
    lifecycle_by_tier: dict[str, float] = {}
