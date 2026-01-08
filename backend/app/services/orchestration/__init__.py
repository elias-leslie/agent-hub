"""Multi-agent orchestration services.

Provides patterns for:
- Subagent spawning with isolated contexts
- Parallel execution
- Maker-checker verification
- Roundtable collaboration (ported from SummitFlow)
"""

from .subagent import SubagentManager, SubagentConfig, SubagentResult
from .parallel import ParallelExecutor, ParallelTask, ParallelResult
from .maker_checker import MakerChecker, VerificationResult, CodeReviewPattern
from .roundtable import (
    RoundtableService,
    RoundtableSession,
    RoundtableMessage,
    RoundtableEvent,
    get_roundtable_service,
)

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
