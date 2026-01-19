"""Memory service module using Graphiti knowledge graph."""

from .consolidation import (
    ConsolidationRequest,
    ConsolidationResult,
    consolidate_task_memories,
    crystallize_patterns,
)
from .context_injector import ContextTier, inject_memory_context, parse_memory_group_id
from .graphiti_client import get_graphiti, init_graphiti_schema
from .learning_extractor import (
    ExtractedLearning,
    ExtractionResult,
    ExtractLearningsRequest,
    LearningStatus,
    LearningType,
    extract_learnings,
)
from .promotion import (
    PromoteRequest,
    PromotionResult,
    ReinforcementResult,
    check_and_promote_duplicate,
    get_canonical_context,
    promote_learning,
)
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
    "ExtractLearningsRequest",
    "ExtractedLearning",
    "ExtractionResult",
    "LearningStatus",
    "LearningType",
    "MemoryCategory",
    "MemoryScope",
    "MemoryService",
    "PromoteRequest",
    "PromotionResult",
    "RecordDiscoveryRequest",
    "RecordGotchaRequest",
    "RecordPatternRequest",
    "RecordResponse",
    "ReinforcementResult",
    "SessionContextResponse",
    "check_and_promote_duplicate",
    "consolidate_task_memories",
    "crystallize_patterns",
    "extract_learnings",
    "format_session_context_for_injection",
    "get_canonical_context",
    "get_graphiti",
    "get_memory_service",
    "get_session_context",
    "init_graphiti_schema",
    "inject_memory_context",
    "parse_memory_group_id",
    "promote_learning",
    "record_discovery",
    "record_gotcha",
    "record_pattern",
]
