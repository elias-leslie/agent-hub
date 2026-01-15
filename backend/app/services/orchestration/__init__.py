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
    "CodeReviewPattern",
    # Maker-Checker
    "MakerChecker",
    # Parallel
    "ParallelExecutor",
    "ParallelResult",
    "ParallelTask",
    "RoundtableEvent",
    "RoundtableMessage",
    # Roundtable
    "RoundtableService",
    "RoundtableSession",
    "SubagentConfig",
    # Subagent
    "SubagentManager",
    "SubagentResult",
    "VerificationResult",
    "get_roundtable_service",
]
