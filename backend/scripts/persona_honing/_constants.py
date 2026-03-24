"""Magic string constants for the persona honing loop."""
from __future__ import annotations

# Agent Hub client identity
CLIENT_NAME = "persona-honing-loop"
REQUEST_SOURCE = "backend/scripts/run_persona_honing_loop.py"
CLI_COMMAND = "run_persona_honing_loop"

# Benchmark run kinds
RUN_KIND_HONING_ITERATION = "honing_iteration"
RUN_KIND_HONING_BASELINE = "honing_baseline"
RUN_KIND_HONING_CANDIDATE = "honing_candidate"

# Experiment decisions
DECISION_PROMOTE = "promote"

# Changed-by attribution
CHANGED_BY = "persona-benchmark-honing"

# CLI defaults
DEFAULT_AGENT_SLUG = "persona"
DEFAULT_BASE_URL = "http://localhost:8003"
DEFAULT_PROJECT_ID = "agent-hub"
DEFAULT_BENCHMARK_TASK_TYPE = "wake"
DEFAULT_SEED = 42
DEFAULT_TIMEOUT_SECONDS: float | None = None
DEFAULT_MAX_ITERATIONS = 2
DEFAULT_COHORT_REPETITIONS = 3
DEFAULT_RUNS_PER_CASE = 1
