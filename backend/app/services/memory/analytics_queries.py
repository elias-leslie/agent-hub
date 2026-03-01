"""Database query functions for memory analytics.

Public API — all symbols remain importable from this module for backward compatibility.
Implementation is split across focused sub-modules:
  - _analytics_distributions: tier/scope breakdowns
  - _analytics_scores:        usage aggregates, daily trend, score averages
  - _analytics_top:           top memories, tier-change log
"""

import logging

from ._analytics_distributions import get_scope_distribution, get_tier_distribution
from ._analytics_scores import (
    get_avg_lifecycle_score,
    get_avg_utility_score,
    get_daily_trend,
    get_lifecycle_by_tier,
    get_usage_aggregates,
)
from ._analytics_top import ALLOWED_SORT_FIELDS, get_tier_changes_summary, get_top_memories_query

logger = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_SORT_FIELDS",
    "get_avg_lifecycle_score",
    "get_avg_utility_score",
    "get_daily_trend",
    "get_lifecycle_by_tier",
    "get_scope_distribution",
    "get_tier_changes_summary",
    "get_tier_distribution",
    "get_top_memories_query",
    "get_usage_aggregates",
]
