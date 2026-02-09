"""Session helper utilities - Re-exports from specialized modules.

This module serves as a backward-compatible facade, re-exporting
functions from specialized modules:
- session_tokens: Token calculations and breakdowns
- session_queries: Query filters and statistics
- session_transforms: Data transformations
- session_branching: Fork and promotion operations
"""

# Token calculations
# Branching operations
from app.services.session_branching import (
    calculate_fork_messages,
    copy_events_to_forked_session,
    create_forked_session,
    discard_sibling_sessions,
    prepare_fork_data,
    validate_promotion_eligibility,
)

# Query filters and statistics
from app.services.session_queries import (
    apply_session_filters,
    fetch_session_statistics,
)
from app.services.session_tokens import calculate_agent_token_breakdown

# Data transformations
from app.services.session_transforms import (
    build_session_list_items,
    build_session_response,
    convert_messages_to_response,
)

__all__ = [
    "apply_session_filters",
    "build_session_list_items",
    "build_session_response",
    "calculate_agent_token_breakdown",
    "calculate_fork_messages",
    "convert_messages_to_response",
    "copy_events_to_forked_session",
    "create_forked_session",
    "discard_sibling_sessions",
    "fetch_session_statistics",
    "prepare_fork_data",
    "validate_promotion_eligibility",
]
