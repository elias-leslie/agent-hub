"""
Scoring and demotion logic for adaptive index.

Implements statistical analysis for entry relevance.
"""

import statistics
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adaptive_index import IndexEntry

# Minimum samples required before demotion is considered
# Uses confidence interval approach: need enough data for statistical significance
MIN_SAMPLES_FOR_DEMOTION = 10


def calculate_demotion_threshold(entries: list["IndexEntry"]) -> float | None:
    """
    Calculate dynamic demotion threshold from data distribution.

    Implements: median(all_ratios) - 1_stdev
    Threshold emerges from data, not hardcoded.

    Args:
        entries: List of index entries with usage stats

    Returns:
        Threshold value, or None if insufficient data
    """
    # Need entries with sufficient samples
    eligible = [e for e in entries if e.loaded_count >= MIN_SAMPLES_FOR_DEMOTION]

    if len(eligible) < 3:
        # Not enough data for statistical analysis
        return None

    ratios = [e.relevance_ratio for e in eligible]

    try:
        median = statistics.median(ratios)
        stdev = statistics.stdev(ratios) if len(ratios) > 1 else 0
        threshold = median - stdev

        # Don't allow negative threshold
        return max(0.0, threshold)
    except statistics.StatisticsError:
        return None


def apply_demotion(
    entries: list["IndexEntry"],
    threshold: float | None,
) -> list["IndexEntry"]:
    """
    Apply demotion logic to entries based on relevance ratio.

    Entries below threshold AND with sufficient samples are demoted.

    Args:
        entries: List of index entries
        threshold: Dynamic demotion threshold

    Returns:
        Updated entries with is_demoted set
    """
    if threshold is None:
        # No threshold calculated yet, don't demote anything
        return entries

    for entry in entries:
        # Only demote if we have statistically significant data
        if entry.loaded_count >= MIN_SAMPLES_FOR_DEMOTION:
            entry.is_demoted = entry.relevance_ratio < threshold
        else:
            entry.is_demoted = False

    return entries
