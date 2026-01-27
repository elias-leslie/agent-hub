"""Multi-agent orchestration services.

Provides patterns for:
- Subagent spawning with isolated contexts
- Parallel execution
- Maker-checker verification
"""

from .maker_checker import CodeReviewPattern, MakerChecker, VerificationResult
from .parallel import ParallelExecutor, ParallelResult, ParallelTask
from .subagent import SubagentConfig, SubagentManager, SubagentResult

__all__ = [
    "CodeReviewPattern",
    "MakerChecker",
    "ParallelExecutor",
    "ParallelResult",
    "ParallelTask",
    "SubagentConfig",
    "SubagentManager",
    "SubagentResult",
    "VerificationResult",
]
