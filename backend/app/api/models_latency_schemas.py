"""Pydantic schemas for model latency statistics API endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class ModelLatencyStats(BaseModel):
    """Per-model latency percentile statistics."""

    model: str
    sample_count: int
    p50_ms: float
    p95_ms: float
    p99_ms: float


class LatencyStatsResponse(BaseModel):
    """Response for latency stats endpoint."""

    stats: list[ModelLatencyStats]
