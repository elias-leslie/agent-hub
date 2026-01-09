"""Multi-agent orchestration services.

Provides patterns for:
- Subagent spawning with isolated contexts
- Parallel execution
- Maker-checker verification
- Roundtable collaboration (ported from SummitFlow)
"""

from .maker_checker import CodeReviewPattern, MakerChecker, VerificationResult
from .parallel import ParallelExecutor, ParallelResult, ParallelTask
from .roundtable import (
    RoundtableEvent,
    RoundtableMessage,
    RoundtableService,
    RoundtableSession,
    get_roundtable_service,
)
from .subagent import SubagentConfig, SubagentManager, SubagentResult

__all__ = [
    # Subagent
    "SubagentManager",
    "SubagentConfig",
    "SubagentResult",
    # Parallel
    "ParallelExecutor",
    "ParallelTask",
    "ParallelResult",
    # Maker-Checker
    "MakerChecker",
    "VerificationResult",
    "CodeReviewPattern",
    # Roundtable
    "RoundtableService",
    "RoundtableSession",
    "RoundtableMessage",
    "RoundtableEvent",
    "get_roundtable_service",
]
