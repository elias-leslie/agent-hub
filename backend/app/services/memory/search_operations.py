"""
Search and retrieval operations for memory service.

Facade module that re-exports all search operations for backward compatibility.
"""

# Re-export semantic search
# Re-export context retrieval
from .search_context import get_context_for_query

# Re-export history retrieval
from .search_history import get_session_history

# Re-export pattern/gotcha search
from .search_patterns import get_patterns_and_gotchas
from .search_semantic import search_memory

__all__ = [
    "get_context_for_query",
    "get_patterns_and_gotchas",
    "get_session_history",
    "search_memory",
]
