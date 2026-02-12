"""
Analytics service for cost and truncation aggregation.

Provides query building and data aggregation for analytics endpoints.

This module serves as the public API for the analytics service. All
functionality has been organized into submodules for better maintainability:
- analytics.models: Data models and filters
- analytics.cost_queries: Cost aggregation queries
- analytics.truncation_queries: Truncation aggregation queries

All imports from this module continue to work for backward compatibility.
"""

# Re-export models for backward compatibility
# Re-export cost aggregation functions
from app.services.analytics.cost_queries import (
    aggregate_costs_by_agent,
    aggregate_costs_by_external_id,
    aggregate_costs_by_model,
    aggregate_costs_by_project,
    aggregate_costs_by_session_type,
    aggregate_costs_by_time,
    aggregate_costs_total,
)
from app.services.analytics.models import (
    CostAggregation,
    CostFilters,
    TruncationAggregation,
    TruncationFilters,
)

# Re-export truncation aggregation functions
from app.services.analytics.truncation_queries import (
    aggregate_truncations_by_model,
    aggregate_truncations_by_time,
    aggregate_truncations_total,
    get_recent_truncation_events,
    get_truncation_rate,
)

__all__ = [
    "CostAggregation",
    "CostFilters",
    "TruncationAggregation",
    "TruncationFilters",
    "aggregate_costs_by_agent",
    "aggregate_costs_by_external_id",
    "aggregate_costs_by_model",
    "aggregate_costs_by_project",
    "aggregate_costs_by_session_type",
    "aggregate_costs_by_time",
    "aggregate_costs_total",
    "aggregate_truncations_by_model",
    "aggregate_truncations_by_time",
    "aggregate_truncations_total",
    "get_recent_truncation_events",
    "get_truncation_rate",
]
