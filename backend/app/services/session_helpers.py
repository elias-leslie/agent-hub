"""Session helper utilities - Re-exports from specialized modules.

This module serves as a backward-compatible facade, re-exporting
functions from specialized modules:
- session_tokens: Token calculations and breakdowns
- session_queries: Query filters and statistics
- session_transforms: Data transformations
- session_branching: Fork and promotion operations
- session_operations: CRUD operations
- session_responses: Response building
"""

# CRUD operations
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
from app.services.session_operations import (
    close_session_if_active,
    create_new_session,
    fork_session_at_turn,
    get_or_create_session,
    list_sessions_with_stats,
    promote_session_branch,
)

# Query filters and statistics
from app.services.session_queries import (
    apply_session_filters,
    fetch_session_statistics,
    get_session_or_404,
    get_session_with_events,
    query_session_events,
)

# Response building
from app.services.session_responses import (
    build_event_responses,
    build_full_session_response,
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
    "build_event_responses",
    "build_full_session_response",
    "build_session_list_items",
    "build_session_response",
    "calculate_agent_token_breakdown",
    "calculate_fork_messages",
    "close_session_if_active",
    "convert_messages_to_response",
    "copy_events_to_forked_session",
    "create_forked_session",
    "create_new_session",
    "discard_sibling_sessions",
    "fetch_session_statistics",
    "fork_session_at_turn",
    "get_or_create_session",
    "get_session_or_404",
    "get_session_with_events",
    "list_sessions_with_stats",
    "prepare_fork_data",
    "promote_session_branch",
    "query_session_events",
    "validate_promotion_eligibility",
]
