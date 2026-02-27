"""Shared data models for tool execution benchmarks."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnMetrics:
    """Metrics for a single turn in a multi-turn tool interaction."""

    turn_number: int
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    tool_results: list[str] = field(default_factory=list)
    permission_checks: int = 0
    permission_denials: int = 0


@dataclass
class BenchmarkResult:
    """Aggregated result from running one benchmark approach."""

    approach: str  # "A", "B", "C", "D"
    approach_name: str  # Human-readable name
    total_latency_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    peak_rss_mb: float = 0.0
    subprocess_count: int = 0
    num_turns: int = 0
    turns: list[TurnMetrics] = field(default_factory=list)
    permission_checks: int = 0
    permission_denials: int = 0
    total_cost_usd: float = 0.0
    correct: bool = False
    errors: list[str] = field(default_factory=list)

    def aggregate_turns(self) -> None:
        """Recompute totals from individual turn metrics."""
        self.num_turns = len(self.turns)
        self.total_input_tokens = sum(t.input_tokens for t in self.turns)
        self.total_output_tokens = sum(t.output_tokens for t in self.turns)
        self.total_cache_read_tokens = sum(t.cache_read_tokens for t in self.turns)
        self.total_cache_creation_tokens = sum(t.cache_creation_tokens for t in self.turns)
        self.permission_checks = sum(t.permission_checks for t in self.turns)
        self.permission_denials = sum(t.permission_denials for t in self.turns)
