"""Memory service module using Graphiti knowledge graph."""

from .consolidation import (
    ConsolidationRequest,
    ConsolidationResult,
    consolidate_task_memories,
    crystallize_patterns,
)
from .context_injector import ContextTier, inject_memory_context
from .graphiti_client import get_graphiti, init_graphiti_schema
from .service import (
    MemoryCategory,
    MemoryScope,
    MemoryService,
    get_memory_service,
)
from .tools import (
    RecordDiscoveryRequest,
    RecordGotchaRequest,
    RecordPatternRequest,
    RecordResponse,
    SessionContextResponse,
    format_session_context_for_injection,
    get_session_context,
    record_discovery,
    record_gotcha,
    record_pattern,
)

__all__ = [
    "ConsolidationRequest",
    "ConsolidationResult",
    "ContextTier",
    "MemoryCategory",
    "MemoryScope",
    "MemoryService",
    "RecordDiscoveryRequest",
    "RecordGotchaRequest",
    "RecordPatternRequest",
    "RecordResponse",
    "SessionContextResponse",
    "consolidate_task_memories",
    "crystallize_patterns",
    "format_session_context_for_injection",
    "get_graphiti",
    "get_memory_service",
    "get_session_context",
    "init_graphiti_schema",
    "inject_memory_context",
    "record_discovery",
    "record_gotcha",
    "record_pattern",
]
