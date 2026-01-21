# Memory System Test Plan

**Goal:** Find the sweet spot for JIT context injection before committing to full implementation.
**Primary Focus:** SummitFlow/Agent Hub agentic usage
**Secondary:** Claude Code as learning source

---

## Table of Contents

1. [Test Architecture Overview](#1-test-architecture-overview)
2. [Metrics to Measure](#2-metrics-to-measure)
3. [Test Phases](#3-test-phases)
4. [Phase 1: Baseline Measurement](#phase-1-baseline-measurement)
5. [Phase 2: A/B Testing Framework](#phase-2-ab-testing-framework)
6. [Phase 3: Parameter Tuning](#phase-3-parameter-tuning)
7. [Phase 4: Agentic Validation](#phase-4-agentic-validation)
8. [Implementation Checklist](#implementation-checklist)
9. [Success Criteria](#success-criteria)

---

## 1. Test Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TESTING INFRASTRUCTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │  CLAUDE CODE    │     │  SUMMITFLOW     │     │  AGENT HUB      │       │
│  │  (Learning)     │────▶│  (Orchestrator) │────▶│  (Memory)       │       │
│  └─────────────────┘     └─────────────────┘     └─────────────────┘       │
│         │                        │                       │                  │
│         │  SessionStart hook     │  execute_task()       │  inject_context()│
│         │  saves learnings       │  with external_id     │  tracks usage    │
│         ▼                        ▼                       ▼                  │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                    METRICS COLLECTION                            │       │
│  │  • Task success rate (by context config)                        │       │
│  │  • Memory utilization (loaded vs referenced)                    │       │
│  │  • Token efficiency (context tokens vs output quality)          │       │
│  │  • Latency impact (retrieval + injection time)                  │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                   │                                         │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                    A/B TEST VARIANTS                             │       │
│  │  Variant A: Current (250 tokens, no scoring, string match)      │       │
│  │  Variant B: Enhanced (400 tokens, scoring, hybrid search)       │       │
│  │  Variant C: Minimal (100 tokens, mandates only)                 │       │
│  └─────────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Metrics to Measure

### Primary Metrics (Task Success)

| Metric | Description | Collection Point | Target |
|--------|-------------|------------------|--------|
| **Task Completion Rate** | % of subtasks passing on first attempt | `subtasks.passes` | > 80% |
| **Retry Rate** | Avg retries before success | `tasks.progress_log` | < 1.5 |
| **Error Prevention Rate** | % of tasks avoiding known gotchas | Compare error types | > 70% |
| **Context Relevance** | % of injected memories actually cited | `referenced_count / loaded_count` | > 40% |

### Secondary Metrics (Efficiency)

| Metric | Description | Collection Point | Target |
|--------|-------------|------------------|--------|
| **Injection Latency** | Time to build progressive context | Agent Hub logs | < 500ms |
| **Token Overhead** | Context tokens / total input tokens | `cost_logs` | < 15% |
| **Memory ROI** | Discovery tokens saved / read tokens | `utility_score` | > 5x |
| **Search Precision** | Relevant results / total results | Manual audit | > 60% |

### Agentic-Specific Metrics

| Metric | Description | Collection Point | Target |
|--------|-------------|------------------|--------|
| **Cross-Subtask Learning** | Does fixing subtask N help N+1? | Subtask progression | Measurable |
| **Escalation Rate** | % requiring supervisor escalation | Orchestrator logs | < 20% |
| **Worktree Success** | Clean merge rate | `worktrees` table | > 90% |
| **Verification Pass Rate** | `verify_command` success | `task_criteria.verified` | > 85% |

---

## 3. Test Phases

```
Phase 1: Baseline (1 week)
    └─ Measure current system performance

Phase 2: A/B Framework (2 days)
    └─ Build infrastructure for variant testing

Phase 3: Parameter Tuning (2 weeks)
    └─ Test scoring formula, token limits, decay rates

Phase 4: Agentic Validation (1 week)
    └─ End-to-end with real SummitFlow tasks
```

---

## Phase 1: Baseline Measurement

### 1.1 Instrument Current System

Add metrics collection to existing code (no behavior changes):

```python
# In agent-hub/backend/app/services/memory/context_injector.py

async def inject_progressive_context(...) -> InjectionResult:
    start_time = time.monotonic()

    # Existing injection logic...
    result = await build_progressive_context(...)

    # NEW: Record metrics
    metrics = {
        "injection_latency_ms": (time.monotonic() - start_time) * 1000,
        "mandates_count": len(result.mandates),
        "guardrails_count": len(result.guardrails),
        "reference_count": len(result.reference),
        "total_tokens": result.total_tokens,
        "query": query[:100],  # Truncated for storage
        "session_id": session_id,
        "external_id": external_id,  # Task ID from SummitFlow
    }

    # Store in new metrics table
    await store_injection_metrics(metrics)

    return result
```

### 1.2 Create Metrics Tables

```sql
-- In agent-hub/backend/migrations/

CREATE TABLE memory_injection_metrics (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT NOW(),
    session_id TEXT,
    external_id TEXT,  -- SummitFlow task_id
    project_id TEXT,

    -- Injection metrics
    injection_latency_ms FLOAT,
    mandates_count INT,
    guardrails_count INT,
    reference_count INT,
    total_tokens INT,
    query TEXT,

    -- Variant for A/B testing
    variant TEXT DEFAULT 'baseline',

    -- Outcome (updated after task completion)
    task_succeeded BOOLEAN,
    retries INT,
    memories_cited TEXT[],  -- UUIDs of memories agent cited

    CONSTRAINT fk_session FOREIGN KEY (session_id)
        REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX idx_injection_metrics_external ON memory_injection_metrics(external_id);
CREATE INDEX idx_injection_metrics_variant ON memory_injection_metrics(variant);
CREATE INDEX idx_injection_metrics_created ON memory_injection_metrics(created_at);
```

### 1.3 Baseline Data Collection Script

```python
# scripts/collect_baseline_metrics.py

"""
Run for 1 week to establish baseline performance.
Collects:
- All task executions via SummitFlow
- Memory injection stats
- Task outcomes
"""

import asyncio
from datetime import datetime, timedelta

async def collect_baseline():
    # Get all task executions from past week
    tasks = await get_completed_tasks(
        since=datetime.now() - timedelta(days=7)
    )

    for task in tasks:
        # Get injection metrics for this task
        metrics = await get_injection_metrics(external_id=task.id)

        # Calculate outcome metrics
        outcome = {
            "task_id": task.id,
            "succeeded": task.status == "completed",
            "retries": count_retries(task.progress_log),
            "subtask_first_pass_rate": calc_first_pass_rate(task),
            "escalation_needed": "supervisor" in task.progress_log,
            "verify_passed": all_criteria_verified(task),
        }

        # Correlate with injected memories
        if metrics:
            outcome["memories_loaded"] = metrics.mandates_count + metrics.guardrails_count + metrics.reference_count
            outcome["memories_cited"] = len(metrics.memories_cited or [])
            outcome["citation_rate"] = outcome["memories_cited"] / max(outcome["memories_loaded"], 1)

        await store_baseline_outcome(outcome)

    # Generate report
    return generate_baseline_report()
```

### 1.4 Expected Baseline Output

```markdown
## Baseline Report (Week of 2026-01-21)

### Task Performance
- Total tasks executed: 47
- Success rate: 72%
- Average retries: 2.1
- Escalation rate: 31%

### Memory System
- Average memories injected: 4.2
- Citation rate: 18% (0.76 / 4.2)
- Injection latency (P50): 285ms
- Token overhead: 8% (358 / 4500 avg)

### Problem Areas
- New mandates (st work, st close) never cited: NOT INJECTED
- Gotchas loaded but not cited: 67% waste
- Reference block rarely useful: 12% citation

### Recommendations
- Fix mandate classification (P0)
- Improve relevance scoring
- Consider reducing reference block
```

---

## Phase 2: A/B Testing Framework

### 2.1 Variant Configuration

```python
# agent-hub/backend/app/services/memory/variants.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional

class MemoryVariant(Enum):
    BASELINE = "baseline"      # Current: 250 tokens, string match
    ENHANCED = "enhanced"      # New: 400 tokens, scoring, hybrid
    MINIMAL = "minimal"        # Test: 100 tokens, mandates only
    AGGRESSIVE = "aggressive"  # Test: 600 tokens, all categories

@dataclass
class VariantConfig:
    """Configuration for a memory injection variant."""

    # Token budgets
    mandate_tokens: int = 250
    guardrail_tokens: int = 150
    reference_tokens: int = 100

    # Scoring weights
    semantic_weight: float = 0.4
    bm25_weight: float = 0.2
    recency_weight: float = 0.2
    usage_weight: float = 0.2

    # Scoring thresholds
    min_score: float = 0.35
    recency_window_days: int = 90

    # Search strategy
    use_hybrid_search: bool = False
    use_query_expansion: bool = False

    # Decay rates (half-life in days)
    mandate_decay_days: int = 30
    reference_decay_days: int = 7


VARIANT_CONFIGS = {
    MemoryVariant.BASELINE: VariantConfig(
        mandate_tokens=250,
        guardrail_tokens=150,
        reference_tokens=100,
        use_hybrid_search=False,
        min_score=0.0,  # No filtering
    ),
    MemoryVariant.ENHANCED: VariantConfig(
        mandate_tokens=300,
        guardrail_tokens=150,
        reference_tokens=150,
        semantic_weight=0.4,
        bm25_weight=0.2,
        recency_weight=0.2,
        usage_weight=0.2,
        use_hybrid_search=True,
        min_score=0.35,
        recency_window_days=90,
    ),
    MemoryVariant.MINIMAL: VariantConfig(
        mandate_tokens=150,
        guardrail_tokens=50,
        reference_tokens=0,  # No reference
        use_hybrid_search=False,
    ),
    MemoryVariant.AGGRESSIVE: VariantConfig(
        mandate_tokens=400,
        guardrail_tokens=200,
        reference_tokens=200,
        use_hybrid_search=True,
        use_query_expansion=True,
        min_score=0.25,  # Lower threshold
    ),
}
```

### 2.2 Variant Assignment

```python
# agent-hub/backend/app/services/memory/variant_assignment.py

import hashlib
from typing import Optional

def assign_variant(
    external_id: str,
    project_id: str,
    override: Optional[MemoryVariant] = None
) -> MemoryVariant:
    """
    Deterministic variant assignment based on task ID.
    Ensures same task always gets same variant (for reproducibility).
    """
    if override:
        return override

    # Use task ID hash for deterministic assignment
    hash_input = f"{external_id}:{project_id}"
    hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)

    # 50% baseline, 30% enhanced, 10% minimal, 10% aggressive
    bucket = hash_value % 100

    if bucket < 50:
        return MemoryVariant.BASELINE
    elif bucket < 80:
        return MemoryVariant.ENHANCED
    elif bucket < 90:
        return MemoryVariant.MINIMAL
    else:
        return MemoryVariant.AGGRESSIVE
```

### 2.3 Integration Point

```python
# Modify context_injector.py

async def inject_progressive_context(
    messages: list[Message],
    query: str,
    scope: MemoryScope,
    session_id: str,
    external_id: Optional[str] = None,
    project_id: Optional[str] = None,
    variant_override: Optional[MemoryVariant] = None,
) -> InjectionResult:
    """
    Inject progressive context with A/B variant support.
    """
    # Assign variant
    variant = assign_variant(
        external_id=external_id or "",
        project_id=project_id or "",
        override=variant_override,
    )
    config = VARIANT_CONFIGS[variant]

    # Build context using variant config
    result = await build_progressive_context(
        query=query,
        scope=scope,
        config=config,  # Pass variant config
    )

    # Record metrics with variant
    await store_injection_metrics({
        "variant": variant.value,
        "config": asdict(config),
        # ... other metrics
    })

    return result
```

---

## Phase 3: Parameter Tuning

### 3.1 Parameters to Tune

| Parameter | Range to Test | Baseline | Hypothesis |
|-----------|---------------|----------|------------|
| `mandate_tokens` | 150, 250, 350, 450 | 250 | Higher = more complete rules |
| `min_score` | 0.0, 0.25, 0.35, 0.50 | 0.0 | Higher = less noise |
| `recency_window_days` | 30, 60, 90, 180 | ∞ | 90 optimal for code |
| `semantic_weight` | 0.3, 0.5, 0.7 | N/A | Depends on query quality |
| `usage_weight` | 0.0, 0.1, 0.2, 0.3 | N/A | Higher = learn from usage |

### 3.2 Tuning Experiments

```python
# scripts/run_parameter_sweep.py

"""
Systematic parameter sweep using synthetic tasks.
"""

PARAMETER_GRID = {
    "mandate_tokens": [150, 250, 350],
    "min_score": [0.0, 0.35, 0.50],
    "recency_window_days": [30, 90],
    "use_hybrid_search": [False, True],
}

async def run_parameter_sweep():
    """Run all parameter combinations on test task set."""

    # Get test tasks (completed tasks with known outcomes)
    test_tasks = await get_test_task_set(n=50)

    results = []

    for params in itertools.product(*PARAMETER_GRID.values()):
        config = VariantConfig(**dict(zip(PARAMETER_GRID.keys(), params)))

        # Run all test tasks with this config
        outcomes = []
        for task in test_tasks:
            # Simulate injection with config
            context = await build_progressive_context(
                query=task.first_message,
                scope=MemoryScope.PROJECT,
                config=config,
            )

            # Measure against known task outcome
            outcome = evaluate_context_quality(
                context=context,
                actual_task_errors=task.errors,
                actual_task_success=task.succeeded,
            )
            outcomes.append(outcome)

        # Aggregate results for this config
        results.append({
            "config": asdict(config),
            "avg_relevance": mean(o["relevance"] for o in outcomes),
            "gotcha_coverage": mean(o["gotcha_hit"] for o in outcomes),
            "noise_rate": mean(o["irrelevant_count"] for o in outcomes),
            "latency_p50": percentile([o["latency"] for o in outcomes], 50),
        })

    # Find Pareto-optimal configs
    return find_pareto_optimal(results)
```

### 3.3 Scoring Formula Validation

```python
# Test the multi-factor scoring formula

async def validate_scoring_formula():
    """
    Validate that scoring formula ranks relevant memories higher.
    Uses known task-memory pairs where we know relevance ground truth.
    """

    # Ground truth: tasks with known relevant memories
    test_cases = [
        {
            "task": "Fix ruff linting errors in api.py",
            "expected_top": ["uuid-ruff-config", "uuid-linting-rules"],
            "expected_not": ["uuid-database-patterns"],
        },
        {
            "task": "Add authentication to /api/users endpoint",
            "expected_top": ["uuid-auth-patterns", "uuid-jwt-gotcha"],
            "expected_not": ["uuid-ui-components"],
        },
    ]

    for case in test_cases:
        # Run scoring
        results = await search_with_scoring(
            query=case["task"],
            config=VARIANT_CONFIGS[MemoryVariant.ENHANCED],
        )

        top_5_uuids = [r.uuid for r in results[:5]]

        # Validate
        for expected in case["expected_top"]:
            assert expected in top_5_uuids, f"Expected {expected} in top 5"

        for not_expected in case["expected_not"]:
            assert not_expected not in top_5_uuids, f"Did not expect {not_expected}"

    print("Scoring formula validation passed!")
```

---

## Phase 4: Agentic Validation

### 4.1 End-to-End Test Suite

```python
# tests/integration/test_agentic_memory.py

"""
End-to-end tests for memory system in agentic context.
Tests the full SummitFlow → Agent Hub → Memory → Execution path.
"""

import pytest
from summitflow.services.orchestrator import OrchestratorService
from agent_hub.services.memory import context_injector

class TestAgenticMemory:
    """Test memory system effectiveness for autonomous task execution."""

    @pytest.fixture
    async def test_project(self):
        """Create test project with known memory state."""
        # Seed specific memories for testing
        await seed_test_memories([
            {
                "content": "Always run dt ruff before committing",
                "tier": "mandate",
                "tags": ["linting", "code-quality"],
            },
            {
                "content": "st close auto-runs verify_command for test-type criteria",
                "tier": "mandate",
                "tags": ["cli", "verification"],
            },
            {
                "content": "In pytest, avoid using fixtures that modify global state",
                "tier": "guardrail",
                "tags": ["testing", "pytest"],
            },
        ])
        return await create_test_project()

    async def test_mandate_injection_for_linting_task(self, test_project):
        """
        Given: A task to fix linting errors
        When: Agent Hub injects context
        Then: Linting mandate should be in top 3
        """
        task = await create_test_task(
            project=test_project,
            title="Fix ruff linting errors in backend/app/api/tasks.py",
        )

        # Capture injected context
        context = await context_injector.build_progressive_context(
            query=task.title,
            scope=MemoryScope.PROJECT,
            project_id=test_project.id,
        )

        # Verify linting mandate is present
        mandate_contents = [m.content for m in context.mandates]
        assert any("dt ruff" in c for c in mandate_contents), \
            "Linting mandate should be injected for linting task"

    async def test_gotcha_prevents_known_error(self, test_project):
        """
        Given: A pytest task with known gotcha
        When: Agent executes with injected gotcha
        Then: Should avoid the anti-pattern
        """
        task = await create_test_task(
            project=test_project,
            title="Write tests for user authentication service",
        )

        # Execute with memory injection
        result = await OrchestratorService(test_project).execute_subtask(
            task_id=task.id,
            subtask_id=task.subtasks[0].id,
        )

        # Check that agent didn't use global state fixtures
        # (would be caught by the injected guardrail)
        assert "global_state" not in result.code_changes, \
            "Agent should avoid global state fixtures per injected guardrail"

    async def test_citation_tracking(self, test_project):
        """
        Given: Task executed with memory injection
        When: Agent cites a memory using [M:uuid8] format
        Then: referenced_count should increment
        """
        memory = await create_test_memory(
            content="Use async/await for all database operations",
            tier="mandate",
        )

        initial_ref_count = memory.referenced_count

        # Execute task that should cite this memory
        task = await create_and_execute_task(
            project=test_project,
            title="Refactor sync database calls to async",
        )

        # Check citation tracking
        updated_memory = await get_memory(memory.uuid)
        assert updated_memory.referenced_count > initial_ref_count, \
            "Memory should be cited when relevant"

    async def test_cross_subtask_learning(self, test_project):
        """
        Given: Subtask 1 fails with specific error
        When: Subtask 2 executes
        Then: Error pattern should be available as gotcha
        """
        task = await create_test_task(
            project=test_project,
            title="Implement feature X",
            subtasks=[
                {"title": "Create API endpoint"},
                {"title": "Add validation"},
            ],
        )

        # Simulate subtask 1 failure with learnable error
        await simulate_subtask_failure(
            task_id=task.id,
            subtask_id=task.subtasks[0].id,
            error="TypeError: 'NoneType' object is not subscriptable",
        )

        # Extract learning from failure
        await extract_learnings_from_session(
            external_id=task.id,
            project_id=test_project.id,
        )

        # Execute subtask 2
        context = await context_injector.build_progressive_context(
            query=task.subtasks[1].title,
            scope=MemoryScope.PROJECT,
            project_id=test_project.id,
        )

        # Check that NoneType gotcha is now available
        guardrail_contents = [g.content for g in context.guardrails]
        assert any("NoneType" in c or "None check" in c for c in guardrail_contents), \
            "Learning from subtask 1 failure should help subtask 2"
```

### 4.2 Real Task Validation

```python
# scripts/validate_with_real_tasks.py

"""
Run memory system variants against real SummitFlow tasks.
Uses tasks from the past month as validation set.
"""

async def validate_with_real_tasks():
    """
    Compare variant performance on real historical tasks.
    """
    # Get completed tasks from past month
    tasks = await get_completed_tasks(
        since=datetime.now() - timedelta(days=30),
        project_id="summitflow",
    )

    results = {variant: [] for variant in MemoryVariant}

    for task in tasks:
        for variant in MemoryVariant:
            # Build context using this variant
            context = await build_progressive_context(
                query=task.first_message,
                scope=MemoryScope.PROJECT,
                config=VARIANT_CONFIGS[variant],
            )

            # Evaluate: would this context have helped?
            evaluation = evaluate_context_against_outcome(
                context=context,
                task_errors=task.errors,
                task_retries=task.retry_count,
                task_success=task.status == "completed",
            )

            results[variant].append(evaluation)

    # Generate comparison report
    return generate_variant_comparison(results)
```

### 4.3 Live Canary Test

```python
# Run 10% of real tasks with ENHANCED variant

async def configure_canary():
    """
    Configure 10% canary for ENHANCED variant.
    """
    # Update variant assignment to:
    # 90% BASELINE, 10% ENHANCED

    await update_variant_weights({
        MemoryVariant.BASELINE: 90,
        MemoryVariant.ENHANCED: 10,
    })

    # Monitor for 1 week
    # Alert if ENHANCED success rate drops below BASELINE - 5%
```

---

## Implementation Checklist

### Pre-Testing (P0)

- [ ] Fix `save-learning` API to set `source_description` correctly
- [ ] Promote 4 missing mandates (st work, st close, schema, browser)
- [ ] Add `memory_injection_metrics` table
- [ ] Instrument `inject_progressive_context()` with metrics

### Baseline Phase

- [ ] Deploy instrumentation to production
- [ ] Run baseline collection for 1 week
- [ ] Generate baseline report
- [ ] Identify top 5 problem areas

### A/B Framework

- [ ] Create `VariantConfig` dataclass
- [ ] Implement `assign_variant()` function
- [ ] Add variant parameter to injection flow
- [ ] Create metrics dashboard for variant comparison

### Parameter Tuning

- [ ] Run parameter sweep on historical tasks
- [ ] Validate scoring formula with ground truth
- [ ] Identify optimal config per metric
- [ ] Document Pareto-optimal configurations

### Agentic Validation

- [ ] Create integration test suite
- [ ] Run end-to-end tests with test project
- [ ] Configure 10% canary
- [ ] Monitor canary for 1 week
- [ ] Decide on rollout based on results

---

## Success Criteria

### Minimum Viable Improvement

| Metric | Baseline | Target | Stretch |
|--------|----------|--------|---------|
| Citation Rate | 18% | 35% | 50% |
| First-Pass Success | 72% | 80% | 85% |
| Retry Rate | 2.1 | 1.5 | 1.2 |
| Injection Latency | 285ms | 400ms | 300ms |

### Go/No-Go Decision

**GO** if:
- Citation rate improves by > 50% (18% → 27%+)
- First-pass success improves by > 5% (72% → 77%+)
- Latency stays under 500ms P95
- No increase in escalation rate

**NO-GO** if:
- Citation rate drops
- Success rate drops by > 3%
- Latency exceeds 1000ms P95
- Escalation rate increases by > 10%

---

## Timeline

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1 | P0 Fixes | Mandate classification fixed, 4 mandates promoted |
| 1-2 | Baseline | Instrumentation deployed, data collecting |
| 2 | Baseline | Baseline report generated |
| 3 | A/B Framework | Variant system deployed |
| 3-4 | Parameter Tuning | Optimal config identified |
| 5 | Canary | 10% traffic on ENHANCED |
| 6 | Decision | Go/No-Go based on canary results |

---

## Appendix: Claude Code Integration

### Learning Source (Not Primary Consumer)

Claude Code sessions contribute learnings but don't need optimized retrieval:

```python
# In SessionStart hook (graphiti-client.sh)

# Current: Query with generic "project context"
# Keep as-is: Claude Code gets basic context

# Learning extraction happens at session end:
# - Extract insights from conversation
# - Save as learnings (not mandates initially)
# - Usage tracking promotes to mandate over time
```

### Promotion Path

```
Claude Code Session
    ↓ (extract learning)
Provisional Learning (confidence: 80)
    ↓ (used 10+ times in SummitFlow)
Guardrail (promoted)
    ↓ (used 25+ times, high success)
Mandate (canonical)
```

This ensures Claude Code learnings feed into the system but SummitFlow agentic usage drives what gets promoted to mandates.
